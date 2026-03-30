# Special Thanks

I've been working on Axiom for about nine months. The harness, framework, and key building blocks were in place, but a blog series and a conversation with two good friends helped me get this to where it is today.

**Gummi Hafsteinsson** started programming on a Commodore 64 in Iceland, spent the late 80s in the Amiga demo scene counting cycles, and has an MBA from MIT. He got the first voice search product to market at Google, became VP of Engineering at Siri (pre-acquisition by Apple), founded Emu (acquired by Google), helped build Google Assistant from the ground up, and currently serves as Chairman of Icelandair. His three-part blog series "Am I Human?" crystallized the idea that specs are the new source code.

**Arnar Hrafnkelsson** represented Iceland at the 25th International Physics Olympiad in Beijing (1994), studied at the University of Michigan, and has been working behind the scenes at Google for over two decades. He is a named inventor on multiple US patents, co-authored "Ad Click Prediction: a View from the Trenches" (KDD 2013, which won the Test of Time Award ten years later), and created the Imager library for Perl. A conversation with Arnar shaped this project's approach to adversarial evaluation and termination conditions.

These are two people I've looked to for technical guidance for 30 years. Gummi and I were classmates in high school, in the ECE program at the University of Iceland, and again at MIT. We co-founded Dímon Software together — I was CEO, he was CTO — building software for the first internet-connected mobile phones around the turn of the millennium. Arnar and I grew up on the same street in Iceland and have been friends for roughly 45 years.

Their influence is visible throughout this project: Gummi's insistence that specs are the programming language and that structure must come before speed; Arnar's conviction that a deterministic harness — not the model — must own the loop, and that adversarial evaluation is how you build trust in autonomous systems.

— Hjalti Thorarinsson

---

## Gummi Hafsteinsson — "Am I Human?" Blog Series

Gummi writes a newsletter called [Am I Human?](https://www.gummihaf.com/p/when-specs-become-the-programming) about building software with AI agents. His three-part series on specs as the new source code was the catalyst for Axiom's entire approach. A few quotes that stuck:

> **The new "source code" is no longer Python, C++, or JavaScript. It's the specification.** The specs are what you should care about now. They encode intent, constraints, trade-offs, and structure. The code is an artifact generated downstream — just like assembly was an artifact of C, and machine code was an artifact of assembly.

> **Agents amplify everything.** If your thinking is sloppy, the agent will faithfully scale that sloppiness. If your intent is vague, it will amplify the ambiguity. If your assumptions are wrong, they'll show up everywhere.

> **Speed doesn't prevent mistakes. It industrializes them.**

> Agents don't read minds. They read specs.

> **The constraint is no longer implementation capacity. It's the quality of decisions.**

> The conversation is where ideas are explored. **The spec is where they are anchored.**

> **Speed makes iteration cheap. Structure makes iteration safe.**

Read the full series: [Part 1: "The Specification Is the New Source Code"](https://www.gummihaf.com/p/when-specs-become-the-programming)

---

## Arnar Hrafnkelsson — Notes from a Long Evening

*What follows is distilled from a few hours of conversation between two old friends, two bottles of wine, and a laptop. We covered far more ground than what's here — this is the subset that directly shaped Axiom.*

### On where agentic workflows are actually working

We were talking about where AI agents have moved the needle in practice, and Arnar's view was that the biggest gains aren't in any particular team or product — they're in infrastructure managing itself. Gemini monitoring its own environment, predicting outages, optimizing compute clusters. Instead of an engineer manually tuning a load balancer, an agentic harness manages the variables in a recursive loop. Small teams supporting exponentially growing traffic without a linear increase in headcount.

### On adversarial evaluation

This is the idea that changed the shape of this project. Arnar described a shift from static testing to **Recursive Adversarial Evaluation** — instead of testing a model against fixed benchmarks, you give an "Adversary" agent the job of finding specific failure points. It generates adversarial examples designed to break the target model's logic. Successful breaks get flagged for further training. The models harden each other.

I asked him directly: "So you're saying the reviewer and the builder should never be the same model?" His answer was immediate — not just different models, different providers. The one that writes the code should never be the one that reviews it, and the one that resolves disputes should be a third party entirely. That conversation became the three-role separation in Axiom's adversarial pipeline.

### On harnesses vs. protocols

There's a fundamental skepticism about MCP and similar standardized middleware. The view is that if a model is smart enough, it shouldn't need rigid interaction patterns — those become innovation roadblocks.

**The harness is the vital component.** It provides the runtime environment — state management, security sandboxing, execution loops. Protocols define how to call a tool. Harnesses define when to stop, what to do when things fail, and who owns the memory. That distinction is why Axiom's server is pure Python and owns the loop — the LLM never decides when to stop.

### On termination conditions

I asked about fully autonomous agents — what percentage run without any human oversight? His answer reframed the question entirely. Most systems are governed by **termination conditions**. An agent isn't "unsupervised" — it's given a goal and boundaries. It runs autonomously until the goal is met or a boundary is hit. Not a percentage of human-free agents — **autonomous loops that stop only when their human-defined task is complete or their safety guardrails are violated.**

That framing is now baked into Axiom's runtime: max turns, time limits, failure counts, retry budgets. The server enforces all of them. Neither the human nor the model is trusted to decide when to stop.

### On the economics of frontier AI

We got into whether building on these APIs is sustainable long-term. His point was that the "instability" is misunderstood — at the inference layer, serving models is already profitable. The financial pressure is an R&D scaling problem: profit from current models gets funneled into the next generation of compute. Every release is profitable as a product, but the industry is in a massive capex phase. For users, the real signal is cost-per-token dropping with every generation of specialized hardware.


---

## Sources

- [Icelandair Group board bio for Guðmundur Hafsteinsson](https://www.icelandairgroup.com/about/board)
- [TechCrunch profile noting that Gummi founded and ran Dímon before Google](https://techcrunch.com/2010/03/19/siri-gummi-hafsteinsson/)
- [Athafnafólk podcast episode on Gummi's founding of Dímon](https://podcasts.apple.com/us/podcast/76-gu%C3%B0mundur-hafsteinsson-frumkv%C3%B6%C3%B0ull/id1291310179?i=1000683916194)
- [Origo annual report board bio for Hjalti Thórarinsson](https://arsskyrsla2018.origo.is/en/)
- [Marel leadership transition announcement](https://marel.com/en/news/vidar-erlingsson-appointed-evp-of-software-solutions/)
- [LinkedIn: Hjalti Thorarinsson](https://www.linkedin.com/in/hjalti/)
