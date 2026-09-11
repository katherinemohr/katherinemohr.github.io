---
layout: post
title: "Unix pipe internals"
subtitle: "Ceci est une (unix) pipe"
tags:
  - unix
hn:
draft: true
---



### Named vs unnamed

### how data gets passed

### forking blah


## Optimizations

### Buffering
https://jvns.ca/blog/2024/11/29/why-pipes-get-stuck-buffering/

### Parallelism
falls out of the fork()

### Input size? 
16KiB by default iirc if you're like catting or wtv

### ksplice?

### SIGPIPE early end
