import Lake
open Lake DSL

package «capri-pvnp-formalization» where
  version := v!"0.1.0"

@[default_target]
lean_lib PvNP where
  roots := #[`PvNP]
