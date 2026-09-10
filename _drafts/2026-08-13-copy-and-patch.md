---
layout: post
title: "Copy-and-Patch Compilation"
subtitle: "Subtitle"
tags:
  - paper
hn:
draft: true
---

[Copy-and-Patch Compilation](https://fredrikbk.com/publications/copy-and-patch.pdf)

## Background/Motivation

JIT compilers always face a tension between compiling fast and compiling fast code. 
With fewer optimization passes, compilation will be fast, but the resulting executable will be slow.
And inversely, with more optimization passes, compilation will be slow, but the resulting executable will be fast. 
To deal with this, JIT compilers
{%sidenote 'v8_blog' "I'm a big fan of the [v8 blog](https://v8.dev/blog) to see different optimizations JIT compilers use."%}
are often tiered, where a first pass will emit unoptimized code, and then hot paths are recompiled in the background and swapped in on-the-fly.
Likewise, query compilers in databases suffer from the same tradeoff and employ tiered execution strategies to minimize startup delay and maximize execution performance.

Web browsers often use baseline compilers {%sidenote 'baseline' "aka template JITs"%} to minimize startup delay. Baseline compilers directly translate bytecode to machine code, often getting better performance than optimizing compilers with optimizations disabled.


## What is the research?

Here is a couple paragraph overview. 

If I want sidenotes, I can do it like this
{%sidenote 'sidenote' "See [example link](https://docs.kernel.org/admin-guide/mm/zswap.html)."%}.

## What are the paper's contributions?

The paper makes some contributions:

- New layer of abstraction
- Some use case that works better in this abstraction
- Numbers

## How does the system work?

### Subsection

Here's a figure

{% maincolumn 'assets/skeleton/solver_comparison.png' '' %}

## How is the research evaluated?

Evaluations!

Probably more subsections!

## Conclusion

One paragraph tld;r.

Fin.
