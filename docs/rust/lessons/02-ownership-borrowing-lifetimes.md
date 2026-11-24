# Lesson 02 — Ownership, borrowing, lifetimes and slices

## Learning objective

Understand the compiler's memory-safety contract well enough to design Rust APIs without unnecessary cloning, dangling references, or accidental aliasing.

## 1. Ownership

Every value has one owner at a time. When the owner leaves its drop scope, the value is dropped. Moving a non-Copy value transfers ownership; the old binding can no longer be used. Copy types such as small integers are copied by value. Clone explicitly duplicates a value and may allocate or copy a large amount of data.

A move is not automatically a deep copy. For a Vec, the vector's pointer/length/capacity metadata moves; the heap allocation is not duplicated. Clone of a Vec duplicates its elements and allocates a new buffer.

## 2. Borrowing

A reference accesses a value without owning it:
- Shared borrow: &T. Multiple shared borrows may coexist while the value is not mutably borrowed.
- Mutable borrow: &mut T. It provides exclusive access while active; competing aliases that could observe or mutate the same value are rejected.
- A shared borrow cannot be used to mutate the referent.
- A mutable borrow prevents other conflicting borrows for the duration of the active borrow.
- The borrow checker uses actual use/liveness, not simply the visual end of a block; non-lexical lifetimes often end a borrow after its last use.

The practical rule: many readers or one writer, not simultaneous readers plus a writer to the same location. This prevents data races in safe Rust.

## 3. Lifetimes

Every reference has a lifetime: the period during which it is valid. Most lifetimes are inferred. Explicit lifetime parameters describe relationships between references; they do not extend the underlying data's life and do not allocate or copy data.

Example:

    fn longest<'a>(left: &'a str, right: &'a str) -> &'a str {
        if left.len() >= right.len() { left } else { right }
    }

The returned slice is guaranteed to be valid for the shared lifetime 'a. The caller still must supply inputs that live long enough.

A dangling reference is rejected because a reference cannot outlive its referent. A struct that stores references usually needs lifetime parameters. 'static means the reference is valid for the entire program duration, not that every value should be made static.

## 4. Slices and strings

- String owns UTF-8 text; str is a dynamically sized string slice type.
- &str borrows text; it can point to a String or a string literal.
- Vec<T> owns a growable contiguous sequence; &[T] borrows a contiguous sequence.
- Prefer &str over &String and &[T] over &Vec<T> in general-purpose read-only function parameters.
- A slice stores a pointer and length, not an owned copy.
- String indexing by arbitrary integer is intentionally unavailable because UTF-8 characters have variable byte lengths. Byte offsets used for string slices must be valid UTF-8 boundaries.

## 5. Drop and RAII

Owned values clean up when their drop scope ends. Drop can run custom cleanup; fields are then dropped according to the language's destructor rules. RAII ties resource lifetime to ownership, so files, locks and buffers can be released automatically even on early returns.

Do not call drop manually as a routine memory-management strategy. Prefer ownership and scopes. Smart pointers and custom Drop implementations are advanced tools with explicit invariants.

## 6. Applied to CCEL

Grid owns one Vec<u8>. It exposes:
- cells() -> &[u8], a shared borrowed view of the complete contiguous buffer.
- rows(), an iterator over borrowed row slices.
- row(index) -> Option<&[u8]>, a bounds-checked borrowed row view.

The row method uses lifetime elision: its returned reference is tied to &self. It does not clone the row and cannot outlive the Grid. The test suite verifies both valid row views and out-of-range behavior.

Transformations take &Grid, read through shared borrows, allocate a separate output buffer, and return an owned Grid. This design avoids unsafe pointers and makes aliasing rules explicit.

## Common mistakes to avoid

- Cloning a Vec merely to pass data to a read-only function.
- Returning a reference to a local value.
- Assuming lifetime annotations extend the life of an object.
- Holding a mutable borrow while trying to read or borrow the same value elsewhere.
- Treating String byte offsets as Unicode character indices.
- Replacing a borrow with 'static to silence a compiler error.
- Using unsafe code before a safe ownership-based design has been considered.

## Exercises

1. Predict which binding owns a String after passing it by value to a function.
2. Rewrite a function taking &String to accept &str and explain which callers become possible.
3. Rewrite a function taking &Vec<u8> to accept &[u8].
4. Explain why two &Grid borrows can coexist but a simultaneous &mut Grid conflicts.
5. Implement a function that returns a row slice from a flat matrix, with overflow-safe bounds checks.
6. Explain why the returned row from Grid::row cannot outlive the Grid.
7. Write a longest function with a shared lifetime parameter and explain what it does not guarantee.
8. Explain why &s[0..1] can panic for some Unicode strings.
9. Describe when moving a Vec is cheaper than cloning it.
10. Explain how RAII releases a resource when a function returns early.

## Retrieval questions

- What exactly moves when a Vec is moved?
- What is the difference between Copy and Clone?
- What aliasing rule distinguishes &T and &mut T?
- What do lifetime parameters describe, and what do they not do?
- Why should an API usually accept &str rather than &String?
- Why does a slice not own the elements it references?
- How does Grid::row tie the returned reference to self?

## Status

Applied and tested in CCEL. Mark as tested only; perform a delayed retrieval check before marking retained.
