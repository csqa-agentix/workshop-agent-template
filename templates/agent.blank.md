# Agent: <give it a name>

<!-- Copy this to my_agent/prompts/agent.md. The model follows it like a job description. Write plain English.
     Rule of thumb: if you can say it in a sentence, put it HERE, not in Python. -->

## Mission
<One short paragraph: what is this agent for, and who reads its result?>

## Tools and when to use them
<!-- One line per tool: name – when to use it. The model also reads each tool's docstring. -->
- `tool_name` – <when / why>

## Phases  (the path the agent follows)
<!-- 3-6 phases. For each: what to do, which tools, and a "Done when" so the agent knows to move on. -->
1. **<Phase>** – <what to do>. *Done when:* <observable condition>
2. **<Phase>** – <…>. *Done when:* <…>

## Rules  (things it must always / never do)
- <Rule>. <!-- Anything that must NEVER happen: ALSO enforce it in app/guardrails.py -->

## Escalate (hand over to a human) when
- <Situation where the agent must not guess>

## Final answer format
<Exactly what the last message must contain. Plain text for a human, e.g. three lines: result · evidence · what a human must decide.>

<!-- Optional: also ask for machine-readable output. It is saved as "structured" in result.json and sent over A2A:
     "End your answer with a fenced json block: {\"verdict\": \"...\", \"confidence\": \"high|medium|low\", \"evidence\": [\"file:line ...\"]}" -->
