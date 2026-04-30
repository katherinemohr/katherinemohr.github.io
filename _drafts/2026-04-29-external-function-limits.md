---
layout: post
title: "A brief history of C function names"
subtitle: "Because names like `strpbrk` are so self-explanatory"
categories:
tags:
  - c
draft: true
---

I was chatting with some friends the other day and offhandedly mentioned the
[historical 6-character limit to external function names in ANSI C](TODO: link)
and realized that this is not common knowledge.

So, let's take a walk down memory lane to see why C stdlib functions have names like 
`strcat` instead of `concat_str` and `strncat` instead of `strcatn`.
