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
├── crypto/
│   ├── __init__.py
│   └── numbers.py             ← modular arithmetic, primality, RSA, Diffie-Hellman
├── signals/
│   ├── __init__.py
│   └── processing.py          ← DFT/FFT, convolution, filters, correlation
├── graph/
│   ├── __init__.py
│   └── algorithms.py          ← UnionFind, MST, Bellman-Ford, max-flow, SCC
├── lambd/
│   ├── __init__.py
│   └── calculus.py            ← lambda terms, alpha/beta/eta, Church encoding, STLC
├── geometry/
│   ├── __init__.py
│   └── core.py                ← vectors, polygons, convex hull, Voronoi, k-d tree
├── rl/
│   ├── __init__.py
│   └── core.py                ← MDPs, Q-learning, SARSA, value/policy iteration, REINFORCE
├── gp/
│   ├── __init__.py
│   └── core.py                ← kernels, Cholesky, Gaussian process regression
├── sat/
│   ├── __init__.py
│   └── solver.py              ← 2-SAT, CDCL with watch literals, DPLL
├── compilers/
│   ├── __init__.py
│   └── core.py                ← lexer, parser, AST, bytecode VM for TinyLang
└── game/
    ├── __init__.py
    └── core.py                ← minimax, Nash equilibrium, Shapley value, zero-sum
├── ml/
    ├── __init__.py
    └── core.py                ← SVMs, decision trees, k-means, naive Bayes
├── odes/
    ├── __init__.py
    └── core.py                ← Euler, Heun, RK4, RK45, ODE systems
├── timeseries/
    ├── __init__.py
    └── core.py                ← moving averages, autocorrelation, AR/MA, ARMA
├── quantum/
    ├── __init__.py
    └── core.py                ← qubits, gates, Bell states, Grover search
├── database/
    ├── __init__.py
    └── core.py                ← B-trees, hash indexes, relational algebra
└── verification/
    ├── __init__.py
    └── core.py                ← model checking, Hoare logic, sequent calculus
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

### Signal Processing (`signals/processing.py`)

The mathematics of signals: transforms, filtering, and convolution.

- **DFT**: `dft` — the discrete Fourier transform, computed directly
  from the definition. `idft` inverts it back.
- **FFT**: `fft` — the radix-2 Cooley-Tukey FFT with bit-reversal
  permutation (zero-pads to the next power of two). `ifft` inverts.
- **Spectral analysis**: `fft_magnitude` (magnitude spectrum),
  `freq_bins` (frequency axis for FFT output), `dominant_frequency`
  (peak non-DC bin).
- **Convolution**: `convolution` — linear convolution of two
  sequences (the operation behind filtering and neural layers).
- **Filters**: `moving_average` (FIR low-pass), `fir_filter`
  (arbitrary FIR filter), both as pure Python.
- **Correlation**: `cross_correlation` — measures similarity between
  two signals at all lag offsets.

### Graph Algorithms (`graph/algorithms.py`)

Graph theory: the structures and algorithms behind networks,
scheduling, and flow.

- **Union-Find**: `UnionFind` — disjoint-set with path compression
  and union by rank.
- **Minimum spanning tree**: `kruskal_mst` (edge-sort based),
  `prim_mst` (priority-queue based).
- **Shortest paths**: `bellman_ford` (handles negative weights,
  detects negative cycles), `floyd_warshall` (all-pairs, adjacency
  matrix).
- **Max flow**: `edmonds_karp` — BFS-based augmenting path algorithm
  (Edmonds-Karp), with `min_cut_edges` for the residual min-cut.
- **Strongly connected components**: `kosaraju_scc` — two-pass
  DFS-based SCC decomposition.
- **Graph coloring**: `graph_color` (greedy), `is_bipartite`
  (2-color check via BFS).

### Lambda Calculus & Type Theory (`lambd/calculus.py`)

The untyped lambda calculus and simply typed lambda calculus — the
foundation of functional programming and type systems.

- **Terms**: `var`, `abs`, `app` — the three term constructors.
  Term representation as nested tuples `('var', name)`,
  `('abs', param, body)`, `('app', func, arg)`.
- **Predicates**: `is_var`, `is_abs`, `is_app`.
- **Free variables**: `free_vars` — computes the free variables of
  a term.
- **Alpha conversion**: `alpha_convert` — rename bound variables.
- **Beta reduction**: `beta_reduce` (one-step), `beta_reduce_all`
  (until normal form), `beta_normal_form` (normalize to NF).
- **Eta reduction**: `eta_reduce`, `beta_eta_normal_form` —
  full normalization with eta conversion.
- **Church encoding**: `church_true`, `church_false`, `church_if`
  (booleans as selectors); `church_zero`, `church_one`,
  `church_succ`, `church_add`, `church_multiply`, `church_pred`
  (numerals as iteration); `church_and`, `church_or`, `church_not`
  (boolean logic as pure lambda terms); `church_to_int` (decode a
  Church numeral back to an integer).
- **Int conversion**: `int_to_church` — build a Church numeral from
  a Python integer.
- **Simply typed lambda calculus**: `base_type`, `arrow_type`,
  `type_equals`, `type_pretty` (types); `t_var`, `t_abs`, `t_app`
  (typed terms); `infer_type` (Hindley-Milner-style inference),
  `check_type` (bidirectional type checking), `unify` (unification
  for type inference), `STLC` (the simply typed lambda calculus
  evaluator).

### Computational Geometry (`geometry/core.py`)

Spatial reasoning: shapes, hulls, and spatial data structures.

- **Vector ops**: `v_add`, `v_sub`, `v_scale`, `v_dot`, `v_cross`,
  `v_norm`, `v_dist`, `v_dist_sq`, `v_normalize`, `v_angle` —
  the 2D vector toolkit.
- **Lines and polygons**: `line_intersection`, `segment_intersect`
  (orientation-based), `polygon_area` (shoelace), `polygon_perimeter`,
  `point_in_polygon` (ray casting), `polygon_centroid`.
- **Convex hull**: `convex_hull` (monotone chain / Andrew's algorithm),
  `is_convex` (turn-direction check).
- **Voronoi diagram**: `nearest_site`, `voronoi_cell_bounds`
  (grid-sampled), `voronoi_diagram`.
- **k-d tree**: `KDTree` with `nearest` and `k_nearest` for
  nearest-neighbor queries in 2D.

### Reinforcement Learning (`rl/core.py`)

The mathematics of learning from rewards: agents, environments,
and the algorithms that train them.

- **Policies**: `epsilon_greedy` (with tie-breaking),
  `softmax_policy` (temperature-controlled).
- **Q-learning**: `q_learning_update` (off-policy), `sarisa_update`
  (on-policy SARSA) — the core update rules for value-based RL.
- **Planning**: `value_iteration` (Bellman backup to convergence),
  `extract_policy` (greedy policy from value function),
  `policy_iteration` (alternating evaluation and improvement).
- **Policy gradient**: `reinforce_update` (REINFORCE, Monte Carlo
  policy gradient for binary softmax policies).
- **GridWorld**: `GridWorld` — the classic 4×4 gridworld MDP with
  goal (+1), pit (-1), and boundary handling.
- **Training**: `train_q_learning` (full Q-learning training loop),
  `evaluate_q_policy` (success-rate evaluation).

### Gaussian Processes (`gp/core.py`)

Bayesian non-parametric regression: the mathematics of kernel
methods and uncertainty.

- **Kernels**: `rbf_kernel` (Gaussian), `linear_kernel`,
  `matern_kernel` (ν = 0.5, 1.5, 2.5, general), `periodic_kernel`.
- **Linear algebra**: `gram_matrix`, `cholesky_decompose`
  (returns None if not positive definite), `cholesky_solve`,
  `forward_substitute` (for GP prediction formulas).
- **GaussianProcess**: `fit` (Cholesky-based), `predict` (posterior
  mean and variance), `log_marginal_likelihood` — the full GP
  regression pipeline with exact inference.
- **Hyperparameter optimization**: `optimize_hyperparameters`
  (gradient descent on log marginal likelihood for RBF length scale).

### SAT Solving (`sat/solver.py`)

Boolean satisfiability: from linear-time 2-SAT to modern CDCL.

- **2-SAT**: `solve_2sat` — linear-time algorithm via implication
  graphs and SCC (Kosaraju). Returns a satisfying assignment or None.
- **CDCL**: `CDCLSolver` — Conflict-Driven Clause Learning with
  watch literals, BCP (boolean constraint propagation), VSIDS-style
  variable ordering, and 1-UIP clause learning.
- **DPLL**: `dpll_solve` — simple recursive DPLL for comparison.
- **Utilities**: `var_of`, `neg`, `to_clause_str`.

### Compilers (`compilers/core.py`)

Building a compiler from scratch: the full pipeline from source
code to executing bytecode.

- **Lexer**: `Lexer` — tokenizes TinyLang source into `Token`
  objects. Supports numbers, strings, identifiers, keywords,
  operators, and comments.
- **Parser**: `Parser` — recursive descent parser producing an
  AST. Supports expressions, `let` bindings, `def` functions,
  `if`/`else`, `while`, `print`, and `return`.
- **AST nodes**: `NumberLiteral`, `StringLiteral`, `BoolLiteral`,
  `Ident`, `BinOp`, `UnaryOp`, `Assign`, `LetStmt`, `IfStmt`,
  `WhileStmt`, `ForStmt`, `ReturnStmt`, `PrintStmt`, `FuncDef`,
  `Call`, `Program`.
- **Compiler**: `Compiler` — compiles the AST to stack-based
  bytecode (`LOAD_CONST`, `LOAD_VAR`, `LOAD_ARG`, `STORE_VAR`,
  arithmetic/comparison ops, `JUMP`, `JUMP_IF_FALSE_POP`, `CALL`,
  `RETURN`, `PRINT`).
- **VM**: `VM` — stack-based bytecode virtual machine that executes
  the compiled code with global variables, function calls, and
  control flow.
- **Top-level**: `compile_and_run` — one-call pipeline: source →
  tokens → AST → bytecode → execution.

### Game Theory (`game/core.py`)

The mathematics of strategic interaction: equilibria, dominance,
and cooperation.

- **Game representation**: `make_zero_sum_game`, `make_bimatrix_game`
  — build games from payoff matrices.
- **Best response**: `best_response` — optimal response to an
  opponent's mixed strategy.
- **Dominance**: `strictly_dominated`, `weakly_dominated`,
  `eliminate_dominated` — iterative elimination of dominated strategies.
- **Nash equilibrium**: `nash_equilibrium_2p` (pure-strategy NE),
  `mixed_nash_equilibrium_2x2` (closed-form mixed NE for 2×2 games).
- **Zero-sum games**: `zero_sum_game_value` (LP-based game value),
  `zero_sum_game_optimal_mixed` (optimal mixed strategy),
  `fictitious_play_strategy` (iterative fictitious play approximation).
- **Cooperative games**: `shapley_value` (fair allocation of
  surplus), `check_correlated_equilibrium` (verify CE conditions).

### Machine Learning (`ml/core.py`)

Supervised and unsupervised learning: the algorithms behind
classification and clustering.

- **SVMs**: `svm_train` (linear soft-margin SVM via sub-gradient
  descent), `svm_predict`, `svm_decision_function` — the support
  vector machine with hinge loss.
- **Decision trees**: `gini_impurity`, `entropy`,
  `information_gain` — the split criteria; `build_decision_tree`
  (CART-style with best-split search), `decision_tree_train`,
  `decision_tree_predict` — full tree construction and inference.
- **k-means**: `kmeans_plusplus_init` (smart initialization),
  `kmeans` (Lloyd's algorithm), `silhouette_score` — clustering and
  evaluation.
- **Naive Bayes**: `GaussianNaiveBayes` (continuous features with
  Laplace-smoothed variances), `MultinomialNaiveBayes` (discrete
  count features with additive smoothing) — the two classic variants.

### Differential Equations (`odes/core.py`)

Numerical solution of ordinary differential equations: from the
simplest method to adaptive step control.

- **Euler's method**: `euler` — first-order explicit integrator.
- **Heun's method**: `heun` — second-order (RK2 / improved Euler).
- **Runge-Kutta 4**: `rk4` — the standard fourth-order method.
- **Adaptive RK45**: `rk45` — Richardson extrapolation error
  control with adaptive step sizing.
- **Systems**: `euler_system`, `rk4_system` — solve coupled ODEs;
  `second_order_to_first` — convert y'' = f(t, y, y') to a first-order
  system.
- **Analytical solutions**: `exponential_decay_solution`,
  `harmonic_oscillator_solution`, `logistic_growth_solution` — for
  verifying numerical results.

### Time Series Analysis (`timeseries/core.py`)

Modeling and forecasting sequential data: autocorrelation, ARIMA
components, and decomposition.

- **Moving averages**: `simple_moving_average`,
  `exponential_moving_average`, `weighted_moving_average` — smoothing
  and trend extraction.
- **Autocorrelation**: `autocorrelation`, `autocorrelation_function`,
  `partial_autocorrelation` — ACF and PACF for model identification.
- **AR models**: `ar_yule_walker` (Yule-Walker estimation),
  `ar_predict` — autoregressive modeling and forecasting.
- **MA models**: `ma_predict`, `ma_theoretical_acf` — moving-average
  theoretical ACF and forecasting.
- **ARMA**: `ARMAModel` — combined AR+MA with forecasting.
- **Stationarity**: `adf_test` (Augmented Dickey-Fuller),
  `linear_detrend`, `seasonal_decompose` — preprocessing and testing.

### Quantum Computing (`quantum/core.py`)

Quantum mechanics and quantum algorithms: from qubits to Grover's
search.

- **States**: `zero_state`, `basis_state`, `state_normalize`,
  `state_probability`, `state_expectation` — quantum state vectors
  and observables.
- **Gates**: `apply_x`, `apply_y`, `apply_z`, `apply_h`, `apply_s`,
  `apply_t`, `apply_cnot` — single-qubit and two-qubit gate
  application on n-qubit states.
- **Bell states**: `bell_state`, `create_bell_pair` — entanglement
  generation and verification.
- **Circuits**: `QuantumCircuit` — fluent circuit builder with
  measurement.
- **Amplitude amplification**: `grover_diffusion_operator`,
  `amplitude_amplification`, `grover_search` — Grover's search
  algorithm.
- **Utilities**: `state_fidelity`, `max_probability` — state
  comparison and measurement analysis.

### Database Internals (`database/core.py`)

The data structures behind relational databases: indexing, tree
structures, and relational algebra.

- **B-trees**: `BTree`, `BTreeNode` — balanced search tree with
  insertion, search, range search, and in-order traversal.
- **Hash indexes**: `HashIndex` (separate chaining),
  `OpenAddressingHash` (linear probing) — two index structures.
- **Relational algebra**: `Relation` with `project`, `select`,
  `union`, `intersect`, `difference`, `natural_join`, `theta_join` —
  the algebraic operations on relations.
- **SimpleDB**: `SimpleDB` — in-memory database with table creation,
  insert, and query execution.

### Formal Verification (`verification/core.py`)

Proving correctness of systems: model checking, Hoare logic, and
proof systems.

- **Kripke structures**: `KripkeStructure`, `bfs_reachable` — state
  space model for temporal logic.
- **LTL model checking**: `lt_check_always` (A□),
  `lt_check_eventually` (EF), `lt_check_exists_always` (E□),
  `lt_check_until` (AU) — temporal property verification.
- **Bounded model checking**: `bounded_model_check` — bounded
  verification within a step limit.
- **Hoare logic**: `HoareTriple`, `weakest_precondition`,
  `assignment_wp`, `sequential_wp`, `hoare_assignment` — deductive
  program verification.
- **GCL**: `GuardedCommand`, `GCLProgram` — Dijkstra's guarded
  command language with weakest precondition computation.
- **Sequent calculus**: `Sequent`, `ProofSystem` — propositional
  proof system with and/or/not/imp rules.
- **Invariants**: `check_inductive_invariant`,
  `check_safety_property` — inductive and reachability-based
  invariant checking.

## Running the Tests

```bash
python3 -m unittest discover -s tests -p "test_training_*.py" -v
```

The test suite (605 tests) covers every function and class above,
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

- **Deep learning**: backpropagation, MLPs, CNNs, RNNs, backprop
  through time.
- **Algorithms**: sorting (quicksort, mergesort, heapsort), advanced
  data structures (segment trees, Fenwick trees, treaps).
- **Computational complexity**: NP-completeness proofs, reductions,
  approximation algorithms.
- **Number theory**: continued fractions, LLL lattice reduction,
  elliptic curve cryptography.
- **Optimization**: interior point methods, convex optimization,
  ADMM, distributed SGD.
- **Probability**: measure theory, stochastic processes (Poisson,
  Brownian motion), filtering (Kalman, particle filters).
- **Computational geometry**: Delaunay triangulation, range trees,
  sweep-line algorithms.
- **Quantum algorithms**: Shor's algorithm, quantum Fourier
  transform, variational quantum algorithms.
