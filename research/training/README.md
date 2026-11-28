# Self-Training Curriculum

An executable, stdlib-only study program covering the foundations of
large language models, logic, mathematics, probability, theory of
computation, and optimization.

Each module is real, runnable Python code — not prose. The curriculum
is designed for self-training: read the code, run it, understand the
math, then extend it.

## Structure

```
research/training/
├── README.md                  ← this file
├── __init__.py                ← top-level re-exports (~140 symbols)
├── logic/
│   ├── __init__.py
│   └── propositional.py       ← propositional logic, SAT, resolution, FOL
├── math/
│   ├── __init__.py
│   └── foundations.py         ← linear algebra, calculus, stats, combinatorics
├── llm/
│   ├── __init__.py
│   └── core.py                ← softmax, attention, layer norm, BPE, transformers
├── probability/
│   ├── __init__.py
│   └── foundations.py         ← Bayes, Markov chains, Monte Carlo, Gibbs
├── theory/
│   ├── __init__.py
│   └── computation.py         ← DFA/NFA, regex, Turing machines, graphs, DP
├── optimization/
│   ├── __init__.py
│   └── methods.py             ← root finding, line search, CG, SA, GA, LR schedules
├── info/
│   ├── __init__.py
│   └── theory.py              ← entropy, mutual information, Huffman coding
├── retrieval/
│   ├── __init__.py
│   └── core.py                ← TF-IDF, cosine similarity, inverted index, BM25
└── crypto/
    ├── __init__.py
    └── numbers.py             ← modular arithmetic, primality, RSA, Diffie-Hellman
```

## Modules

### Logic (`logic/propositional.py`)

Propositional and first-order logic from the ground up.

- **Formula AST**: `var`, `negate`, `conjoin`, `disjoin`, `imply`,
  `biconditional` — build well-formed formulas as tuples.
- **Evaluation**: `evaluate` under an assignment; `truth_table`
  generates all rows.
- **CNF & SAT**: `to_cnf` (Tseitin-style), `cnf_clauses`, `dpll_sat`
  — a complete DPLL SAT solver with unit propagation.
- **Resolution**: `resolve` computes resolvents; `resolution_refute`
  checks unsatisfiability by deriving the empty clause.
- **First-order logic**: `const`, `fvar`, `func` for terms;
  `substitute`, `occurs_in`, `unify` — full unification with the
  occurs-check.

### Mathematics (`math/foundations.py`)

The mathematical toolkit underlying ML and quantitative reasoning.

- **Linear algebra**: `dot`, `vector_add`, `vector_scale`,
  `vector_norm`, `mat_transpose`, `mat_multiply`, `mat_identity`,
  `mat_determinant` (LU with partial pivoting), `mat_inverse`
  (Gauss-Jordan), `power_iteration` (dominant eigenvalue),
  `svd_2x2`.
- **Calculus**: `numerical_derivative` (central difference),
  `numerical_gradient`, `numerical_jacobian`.
- **Statistics**: `mean`, `variance`, `stddev`, `covariance`,
  `correlation`, `linear_regression`, `r_squared`.
- **Probability distributions**: `binomial_pmf`, `binomial_mean`,
  `binomial_variance`, `normal_pdf`, `normal_cdf` (via `math.erf`).
- **Combinatorics**: `power_set`, `cartesian_product`, `factorial`,
  `permutations_count`, `combinations_count`.

### LLM (`llm/core.py`)

The core mathematics of large language models, implemented from scratch.

- **Activations**: `softmax` (numerically stable), `log_softmax`,
  `gelu` (exact via `math.erf`), `relu`.
- **Attention**: `scaled_dot_product_attention` (Q·Kᵀ/√dₖ · V),
  `multi_head_attention` (split-concat multi-head).
- **Normalization**: `layer_norm`, `layer_norm_with_params`
  (gamma/beta).
- **Positional encoding**: `sinusoidal_positional_encoding`
  (the original Transformer formulation).
- **Feed-forward**: `feed_forward` (Linear → GELU → Linear).
- **Tokenization**: `BPETokenizer` — byte-pair encoding with
  train/encode, the algorithm behind GPT/BERT tokenizers.
- **Losses**: `cross_entropy` (via log-softmax), `kl_divergence`,
  `entropy`.
- **Optimizers**: `gradient_descent`, `momentum_descent`, `adam`
  — the three optimizers that train modern models.
- **TransformerBlock**: assembles the pieces into a block
  (study model).

### Probability (`probability/foundations.py`)

Probabilistic reasoning: the language of uncertainty and inference.

- **Bayes**: `conditional_probability`, `bayes_theorem`,
  `total_probability`, `are_independent`.
- **Random variables**: `expectation`, `variance_rv`, `covariance_rv`
  (weighted or uniform).
- **Conjugate priors**: `beta_update`, `beta_mean`, `beta_variance`,
  `normal_update` (normal-normal conjugate).
- **Markov chains**: `transition_matrix_from_counts`,
  `apply_transition`, `steady_state` (power iteration),
  `markov_chain_simulate`.
- **Monte Carlo**: `monte_carlo_estimate` (integrals),
  `monte_carlo_pi` (circle packing).
- **Limit theorems**: `law_of_large_numbers`, `central_limit_theorem`
  (simulations).
- **Gibbs sampling**: `gibbs_sampler` (Metropolis-adjusted, study).

### Theory of Computation (`theory/computation.py`)

What can be computed, and how fast.

- **Finite automata**: `DFA` (accepts/rejects), `NFA` with
  epsilon-closure, `NFA.to_dfa` (subset construction).
- **Regular expressions**: `regex_match` — recursive matcher with
  `.`, `*`, `+`, `?`, `|`, `()`.
- **Turing machines**: `TuringMachine` — configurable TM simulator
  with accept/reject/timeout.
- **Complexity**: `is_polynomial_time` — empirical log-log slope
  check.
- **Graph algorithms**: `bfs`, `dfs`, `dijkstra` (weighted),
  `topological_sort` (Kahn's algorithm).
- **Dynamic programming**: `fib_dp`, `longest_common_subsequence`,
  `knapsack` (0/1).

### Optimization (`optimization/methods.py`)

How to find minima and roots, the engine behind every trained model.

- **Root finding**: `bisection_root`, `newtons_method`,
  `secant_method`.
- **Line search**: `golden_section_search` (unimodal),
  `backtracking_line_search` (Armijo condition).
- **Conjugate gradient**: `conjugate_gradient` (solves Ax=b for
  symmetric positive-definite A).
- **Global search**: `simulated_annealing`, `genetic_algorithm`
  (tournament selection, elitism).
- **Learning-rate schedules**: `step_decay`, `exponential_decay`,
  `cosine_annealing`, `linear_warmup`, `cosine_with_warmup` —
  the schedules used in real training runs.
- **Nelder-Mead**: `nelder_mead` (simplex method, simplified).

### Information Theory (`info/theory.py`)

The mathematics of information: how to quantify, measure, and
compress uncertainty.

- **Entropy**: `shannon_entropy` (bits), `joint_entropy`,
  `marginal_probs`, `conditional_entropy`.
- **Mutual information**: `mutual_information` (I(X;Y) = H(X)+H(Y)−H(X,Y)),
  `normalized_mutual_information` (0 to 1 scale), `information_gain`
  (the decision-tree split criterion).
- **Divergence**: `kl_divergence_bits`, `cross_entropy_bits`,
  `entropy_from_counts`.
- **Huffman coding**: `HuffmanCoder` — builds a prefix-free code tree
  from symbol frequencies, with encode/decode and average code length.
  The foundation of lossless compression.
- **Feature selection**: `mutual_information_feature` — computes MI
  between each feature and a target, the basis of filter-based
  feature selection.

### Information Retrieval (`retrieval/core.py`)

How search engines find and rank documents.

- **Preprocessing**: `tokenize`, `remove_stop_words`,
  `DEFAULT_STOP_WORDS`.
- **TF-IDF**: `term_frequency`, `document_frequency`,
  `inverse_document_frequency`, `tfidf_weights` — the classic
  vector-space model.
- **Similarity**: `cosine_similarity`, `dot_product_sparse`,
  `vector_norm` for sparse document vectors.
- **Inverted index**: `InvertedIndex` — maps terms to documents,
  with AND/OR search. The core structure behind every search engine.
- **BM25**: `BM25Ranker` — the modern standard ranking function
  with tunable k1 and b parameters.
- **Evaluation**: `precision_score`, `recall_score`, `f1_score`,
  `mean_average_precision` — the metrics for ranking quality.

### Number Theory & Cryptography (`crypto/numbers.py`)

The math behind modern cryptography.

- **Modular arithmetic**: `mod_pow` (binary exponentiation),
  `modular_inverse` (extended Euclidean), `euler_phi`,
  `fermat_little_theorem`, `euler_theorem`.
- **GCD**: `gcd` (Euclid's algorithm), `extended_gcd`.
- **Primality**: `is_prime_trial`, `miller_rabin` (probabilistic),
  `find_prime`.
- **Square roots**: `tonelli_shanks` (modular square roots for
  odd primes).
- **RSA**: `RSA` class — key generation, encrypt, decrypt, and
  byte-level encrypt/decrypt.
- **Discrete log**: `baby_step_giant_step` — O(√p) discrete log.
- **Key exchange**: `diffie_hellman_shared` — the Diffie-Hellman
  shared-secret computation.
- **Hashing**: `fnv1a_32`, `fnv1a_64` (FNV-1a), `sha256_hex`,
  `sha256_int`.

## Running the Tests

```bash
python3 -m unittest discover -s tests -p "test_training_*.py" -v
```

The test suite (241 tests) covers every function and class above,
verifying correctness against known mathematical results.

## Design Constraints

- **Stdlib-only**: no dependencies beyond Python's standard library.
  Everything is implemented from scratch for study purposes.
- **No network, no models**: pure computation, fully deterministic
  (seeded RNG where randomness is needed).
- **Study-grade, not production-grade**: these are teaching
  implementations. They demonstrate the algorithms correctly but may
  lack the numerical robustness, error handling, and performance of
  production libraries (NumPy, PyTorch, etc.).

## Extending the Curriculum

The natural next areas to study and implement:

- **Gaussian processes**: kernel methods, Cholesky decomposition,
  posterior prediction.
- **Reinforcement learning**: Q-learning, policy gradient,
  Markov decision processes.
- **Computational geometry**: convex hull, Voronoi diagrams,
  k-d trees.
- **Signal processing**: DFT, FFT, convolution, filtering.
- **Graph theory deep dive**: minimum spanning tree (Kruskal/Prim),
  maximum flow, shortest paths with negative weights (Bellman-Ford).
- **Advanced SAT**: CDCL solver, 2-SAT in linear time.
- **Type theory & lambda calculus**: Church encoding, beta/eta
  reduction, simply typed lambda calculus.
