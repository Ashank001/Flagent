"""
deviation_scorer.py — Session Anomaly Scorer

Scores a production session's tool-call trace against the stored behavioural
baseline fingerprint. Produces a 0-100 anomaly score and a classification.

Scoring formula (4 weighted components):
  1. Cosine distance:  tool-frequency vector vs baseline       (weight: 30%)
  2. Bigram novelty:   % of session bigrams NOT in baseline    (weight: 30%)
  3. Volume anomaly:   unusual repetition of tools             (weight: 25%)
  4. Length z-score:    |session_len - avg| / std, capped at 3  (weight: 15%)

Classification:
  score < 30   -> "normal"
  30 <= score <= 60 -> "warning"
  score > 60   -> "alert"
"""

import math
from collections import Counter


W_COSINE = 0.20
W_BIGRAM = 0.20
W_VOLUME = 0.45
W_LENGTH = 0.15

# z-score cap for length component (z=3 maps to 100)
Z_CAP = 3.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_session(session_trace: dict, fingerprint: dict) -> dict:
    """
    Score a single session trace against the baseline fingerprint.

    Args:
        session_trace: {
            "tools_called":          [str, ...],   # ordered sequence
            "tool_counts":           {str: int},    # per-tool counts this session
            "response_length_words": int,
        }
        fingerprint: {
            "tool_frequency":      {str: float},   # avg calls/session
            "common_bigrams":      {str: int},      # "toolA->toolB": count
            "avg_response_length": float,
            "std_response_length": float,
        }

    Returns:
        {
            "score":          float 0-100,
            "classification": "normal" | "warning" | "alert",
            "components": {
                "cosine_distance": float 0-100,
                "bigram_novelty":  float 0-100,
                "volume_anomaly":  float 0-100,
                "length_zscore":   float 0-100,
            },
        }
    """
    cos = _cosine_distance_score(
        session_trace["tool_counts"], fingerprint["tool_frequency"]
    )
    big = _bigram_novelty_score(
        session_trace["tools_called"], fingerprint["common_bigrams"]
    )
    lzs = _length_zscore_score(
        session_trace["response_length_words"],
        fingerprint["avg_response_length"],
        fingerprint["std_response_length"],
    )
    vol = _volume_anomaly_score(
        session_trace["tool_counts"], fingerprint["tool_frequency"]
    )

    final = W_COSINE * cos + W_BIGRAM * big + W_VOLUME * vol + W_LENGTH * lzs

    if final < 30:
        classification = "normal"
    elif final <= 60:
        classification = "warning"
    else:
        classification = "alert"

    return {
        "score": round(final, 2),
        "classification": classification,
        "components": {
            "cosine_distance": round(cos, 2),
            "bigram_novelty": round(big, 2),
            "volume_anomaly": round(vol, 2),
            "length_zscore": round(lzs, 2),
        },
    }


# ---------------------------------------------------------------------------
# Component 1: Cosine distance (40%)
# ---------------------------------------------------------------------------

def _cosine_distance_score(
    session_tool_counts: dict[str, int],
    baseline_frequency: dict[str, float],
) -> float:
    """
    Cosine distance between session's tool-count vector and baseline's
    average-frequency vector, scaled to 0-100.

    Cosine distance = 1 - cosine_similarity.
    For non-negative vectors this is in [0, 1], so * 100 → [0, 100].
    """
    all_tools = sorted(
        set(list(session_tool_counts.keys()) + list(baseline_frequency.keys()))
    )
    if not all_tools:
        return 0.0

    vec_s = [float(session_tool_counts.get(t, 0)) for t in all_tools]
    vec_b = [float(baseline_frequency.get(t, 0)) for t in all_tools]

    dot = sum(a * b for a, b in zip(vec_s, vec_b))
    mag_s = math.sqrt(sum(a ** 2 for a in vec_s))
    mag_b = math.sqrt(sum(b ** 2 for b in vec_b))

    if mag_s == 0 and mag_b == 0:
        return 0.0  # both empty — identical
    if mag_s == 0 or mag_b == 0:
        return 100.0  # one is empty — maximum divergence

    cosine_sim = dot / (mag_s * mag_b)
    cosine_sim = max(0.0, min(1.0, cosine_sim))  # clamp float noise
    cosine_dist = 1.0 - cosine_sim

    return cosine_dist * 100.0


# ---------------------------------------------------------------------------
# Component 2: Bigram novelty (35%)
# ---------------------------------------------------------------------------

def _bigram_novelty_score(
    tool_sequence: list[str],
    common_bigrams: dict[str, int],
) -> float:
    """
    Percentage of this session's tool-call bigrams that are NOT found in
    the baseline's common_bigrams, scaled to 0-100.

    If the session has < 2 tool calls (no bigrams), returns 0 (no novelty).
    """
    if len(tool_sequence) < 2:
        return 0.0

    session_bigrams = [
        f"{tool_sequence[i]}->{tool_sequence[i + 1]}"
        for i in range(len(tool_sequence) - 1)
    ]

    if not session_bigrams:
        return 0.0

    novel = sum(1 for b in session_bigrams if b not in common_bigrams)
    return (novel / len(session_bigrams)) * 100.0


# ---------------------------------------------------------------------------
# Component 3: Response-length z-score (25%)
# ---------------------------------------------------------------------------

def _length_zscore_score(
    session_length: int | float,
    avg_length: float,
    std_length: float,
) -> float:
    """
    |z-score| of session response length vs baseline mean/std,
    capped at Z_CAP and normalized to 0-100.
    """
    if std_length == 0:
        return 0.0 if abs(session_length - avg_length) < 1 else 100.0

    z = abs(session_length - avg_length) / std_length
    z_capped = min(z, Z_CAP)
    return (z_capped / Z_CAP) * 100.0


# ---------------------------------------------------------------------------
# Component 4: Volume anomaly (25%)
# ---------------------------------------------------------------------------

def _volume_anomaly_score(
    session_tool_counts: dict[str, int],
    baseline_frequency: dict[str, float],
) -> float:
    """
    Score based on unusual repetition of tools or total high volume.
    Normalized to 0-100.
    """
    score = 0.0
    
    # 1. Per-tool volume check
    for tool, count in session_tool_counts.items():
        avg = baseline_frequency.get(tool, 0.0)
        effective_avg = max(1.0, avg)
        ratio = count / effective_avg
        
        # If a single tool is called 2+ times its baseline average
        if ratio >= 2.0:
            score += min(100.0, (ratio - 1.5) * 20.0)
            
    # 2. Total volume check
    total_session = sum(session_tool_counts.values())
    total_avg = sum(baseline_frequency.values())
    effective_total_avg = max(1.0, total_avg)
    
    total_ratio = total_session / effective_total_avg
    if total_ratio >= 2.0:
        score += min(100.0, (total_ratio - 1.5) * 20.0)
        
    return min(100.0, score)
