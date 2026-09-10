---
layout: post
title: "Killer Apps"
subtitle: "an oral history"
categories:
tags:
  - thoughts
---

The other day, I found myself trying to explain to a friend why FlashFill was so important to the field of program synthesis, and the best way I could think to describe it was as a "killer app"
{%- sidenote 'wikipedia' "The [wikipedia article on this](https://en.wikipedia.org/wiki/Killer_application) was a surprisingly fun read!" %}
for the field.

This got me thinking about other killer apps for different fields, since it's not the kind of thing that is well catalogued, except perhaps by citation counts and Test of Time awards, and is instead the kind of thing often off-handedly mentioned by a tenured professor. 

## The Past

Not an academic field, but spreadsheets (specifically [VisiCalc](https://en.wikipedia.org/wiki/VisiCalc)) were the killer app to get desktop computers widely adopted by corporate America.

As such, maybe it's only fitting that (at least what I think of as) the canonical killer app for program synthesis would also be a spreadsheet feature, [FlashFill](https://support.microsoft.com/en-us/excel/using-flash-fill-in-excel). As described in its [POPL'11 paper](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/12/popl11-synthesis.pdf), FlashFill is able to synthesize string manipulation expressions from just a few (even singular) input-output examples. As an example, given "Principles Of Programming Languages" as input and "POPL" as output, FlashFill would synthesize the expression `Loop(𝜆𝑤 : Concatenate(SubStr2(𝑣1 , UpperTok, 𝑤)))` as a generic way of abbreviating inputs. While looking into this, I actually found a [2021 retrospective by Gulwani](https://blog.sigplan.org/2021/09/14/the-story-of-the-flash-fill-feature-in-excel/) that details how he came across this problem and FlashFill's impact over the following decade.

In the area of probablistic programming, I often think of [TrueSkill](https://en.wikipedia.org/wiki/TrueSkill), a system 
{%- sidenote 'library' "It's also available as a [Python library](https://trueskill.org)!" %} 
for rating players' skills with the goal of creating well-matched games with approximately equal odds of any team winning (particularly in the setting of video games) as being the killer app. I surprisingly had a somewhat hard time finding the [TrueSkill paper](https://arxiv.org/pdf/1308.0689) to link here, so it it maybe worth defining "killer app" in the context of academic fields as a paper/system/technique that allows the _general public_ to utilize foundational concepts from some field, rather than one that is purely foundational within its own bubble
{%- sidenote 'hyperbole' "I actually maybe think of these two papers as niche systems with wide adoption, which feels like a crazy hyperbole." %}
. 

## The Present/Future

I particularly like these examples since they are such nice confined systems with a singular goal, and whose singular goal both 
1. uses core concepts from their field and
2. is tech-transferrable into something that is immediately useful to the general public.

I certainly don't think all research needs to fit into these boxes, and I actually think I tend to rally against #2 in preference of weirder, longer-term research. That said, it is still interesting to think about what are the next "killer apps", particularly in non-AI research?

I don't know, but perhaps the past lends some clues. If you know of any other papers that you'd consider "killer apps", let me know!
