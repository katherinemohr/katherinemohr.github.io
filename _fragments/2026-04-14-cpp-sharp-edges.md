---
layout: post
title: "C++ Arrow Chaining"
subtitle: "I can't believe I got got by the arrow operator"
categories:
tags:
  - cpp
---

In my time as a Five Rings intern mentor, I would send out a "C++ Question of the Day" on Slack every morning
to give the interns something to think about in their downtime. As the weeks went on, I tried to make them trickier
and more corner-casey{% sidenote 'quiz' "I've turned this into [an online quiz](/2026/04/20/cpp-quiz.html)!" %}.
So, I had considered adding a question on [arrow chaining](https://stackoverflow.com/questions/4923270/is-operator-chained-for-pointers),
but I felt like the dummy code I was writing seemed too unlikely to happen in practice and ditched it.

Well, nevermind! I got bit by this the other day, so as punishment, I must write about it.

```cpp
return llvm::TypeSwitch<Operation *, double>(op)
      // simple roofline flop calculation for nested ops
      .Case<linalg::GenericOp, linalg::MapOp, linalg::ReduceOp>(
          [&](auto genericOp) {
            int64_t iters = linalgIters(genericOp);
            double flopsPerIter = 0.0;
            for (Operation &op : genericOp->getBlock()->getOperations()) {
              if (!isa<linalg::YieldOp>(op)) {
                flopsPerIter += estimateFlops(op);
              }
            }
            return flopsPerIter * iters;
          })
      
      // ... more code
      });
```

Note the following line:
```cpp
for (Operation &op : genericOp->getBlock()->getOperations()) {
```

`genericOp` is clearly a reference, so why didn't the arrow cause a compilation error? 

Turns out, the arrow operator has actually been overloaded{% sidenote 'mlirsource' "Link to source: [mlir/include/mlir/IR/OpDefinition.h](https://github.com/llvm/llvm-project/blob/9b8611b1c5b3d454b2c5e052c00f7285d733d496/mlir/include/mlir/IR/OpDefinition.h#L109)" %} for non-pointer types here.

```cpp
// From mlir/include/mlir/IR/OpDefinition.h
class OpState {
public:
  // ...

  /// Shortcut of `->` to access a member of Operation.
  Operation *operator->() const { return state; }
  // ...
};
```

So, the `genericOp->getBlock()` call gets desugared to `genericOp.operator->()->getBlock()`,
which, as we see above, ends up calling `genericOp.state->getBlock()`.

In my case, `genericOp.state->getBlock()` and `genericOp.getBlock()` were semantically different,
leading to runtime errors.

---

This example actually is fairly straightforward, but you could imagine these chaining together like:

```cpp
struct C { void foo(); };
struct B { C* operator->() { return &c; } C c; };
struct A { B  operator->() { return b; } B b; };

A a;
a->foo(); 
// expands to: A::operator->() -> returns B (not a pointer)
//             B::operator->() -> returns C* (raw pointer, stop)
//             C::foo() called on that C*
```
