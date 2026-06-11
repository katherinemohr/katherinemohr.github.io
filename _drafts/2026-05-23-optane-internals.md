---
layout: post
title: "In memoriam: Intel Optane"
subtitle: "A DIMM-wit pokes at the internals of a failed DRAM/NAND hybrid"
tags:
  - optane
hn:
draft: true
---

I've been working on a prototype of a potential type of RAM as part of
[Stanford's Differentiated Access Memory (DAM) Project](https://dam.stanford.edu),
and this project keeps bringing me back to a sadly killed Intel attempt: Optane{% sidenote 'ad_pdf' 
"Or to hear about it from Intel themselves, here is one
of their [marketing materials](https://www.intel.com/content/dam/www/public/us/en/documents/technology-briefs/what-is-optane-technology-brief.pdf#:~:text=Mode%20delivers%20Intel%20Optane%20technology,Unlike%20traditional%20DRAM%2C%20Intel®%20Optane™)."%}.

I tend to run in nerdy tech circles where people know what Optane is
(and have strong opinions on it{% sidenote 'shocking' "shocking, I know!" %}).
That said, the internals of Optane are a bit nebulous, even to friends in these circles,
and I have necessarily become fairly well versed in the design of Optane over the last couple weeks.

So, without further ado,

## What is Optane?

In the most technical jargony terms, Optane is a phase-change memory technology, 3D X-Point, packaged as either an 
M.2 SSD or as a DIMM.

Let's unpack some of the jargon here. 
**Phase-change memory** is a kind of non-volatile memory that physically changes the bit material between a crystalline and amorphous structure to represent 0s and 1s.
Both **M.2** (**M**odule, **2**nd gen?) and **DIMM** (**D**ual **I**n-line **M**emory **M**odule) really just refer to the physical packaging of the hardware. M.2 SSDs are 22mm across, and DIMMs are what you think of when you think of a "stick of ram".

In more hand-wavey terms, Optane was Intel's attempt at building a new storage class that could fit somewhere in between traditional DRAM and SSDs.

### What do 


{% maincolumn 'assets/skeleton/solver_comparison.png' '' %}

## Why wasn't it successful commercially?



## How did Optane (DIMMs) work?

One paragraph tld;r.

Fin.

## References
https://www.sysdevlabs.com/articles/storage-technologies/what-is-intel-optane/
