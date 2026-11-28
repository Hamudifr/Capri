"""Information theory study modules."""

from research.training.info.theory import (
    shannon_entropy, joint_entropy, marginal_probs,
    conditional_entropy, mutual_information,
    normalized_mutual_information, information_gain,
    kl_divergence_bits, cross_entropy_bits, entropy_from_counts,
    HuffmanNode, HuffmanCoder, mutual_information_feature,
)

__all__ = [
    "shannon_entropy", "joint_entropy", "marginal_probs",
    "conditional_entropy", "mutual_information",
    "normalized_mutual_information", "information_gain",
    "kl_divergence_bits", "cross_entropy_bits", "entropy_from_counts",
    "HuffmanNode", "HuffmanCoder", "mutual_information_feature",
]
