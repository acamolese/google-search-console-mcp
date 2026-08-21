# Evaluating the tool descriptions

Tests prove the tools work. They say nothing about whether a model picks the
right one from a plain-language question, which is the part that actually
determines whether this server is useful in a chat.

That is what this directory is for. It is a manual procedure, not a CI job: it
needs a real property and real data, and the answers depend on the client and
model in use.

## Procedure

1. Copy `questions.example.xml` to `questions.xml` and fill in the answers from a
   property you have access to. Keep the questions phrased the way someone would
   actually ask them — "how did the site do last week", not "call
   gsc_performance_overview".
2. Configure the server in the client under test, with no other MCP server
   connected. A second server with overlapping tools changes the result.
3. Ask each question in a fresh conversation. Record which tools were called, in
   what order, and whether the final answer matches the expected one.
4. Score each pair on two axes, kept separate on purpose:
   - **Tool selection**: did it reach for the right tool, first try?
   - **Answer**: are the numbers right, and does the reasoning hold?

A wrong tool that still produced the right answer is a description problem
waiting to bite. Note it.

## What to do with the result

A question that consistently routes to the wrong tool means the description is
wrong, not the model. Fix the description, then re-run. Tool descriptions are
cached by clients, so a fixed description may need a restart to take effect.

## Format

```xml
<evaluation>
  <qa_pair>
    <question>...</question>
    <answer>...</answer>
  </qa_pair>
</evaluation>
```
