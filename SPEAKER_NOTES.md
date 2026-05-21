NeuroCI — Speaker Notes (Slide-by-slide)

Slide: Title
- Greet audience, introduce yourself and the project
- State demo length and Q&A

Slide: Motivation
- Explain developer friction when CI fails
- Mention average time lost and repeat failure stat
- Quick story to connect

Slide: Problem Statement
- Emphasize the gap: time cost + human context switching
- Why existing tools don't fully solve this

Slide: High-Level Architecture
- Walk through each major component briefly
- Call out multi-LLM support and RAG memory
- Mention infra: Docker / K8s / Helm

Slide: Pipeline Flow
- Step through the 5 stages
- Give a short example mapping to sample fixture

Slide: Failure Categories
- Mention most common patchable categories
- Note which categories are escalated

Slide: Demo Plan
- Explain what will be shown and why it's short
- Mention failure fixture used and expected outcome

Slide: Live Demo (Commands)
- Run `docker compose up -d` before demo
- If internet blocked, show recorded outputs located at `tests/fixtures/expected_patches`

Slide: Results & Metrics
- Show sample metrics; explain confidence threshold and MTTR

Slide: Safety & Policy
- Emphasize OPA gating and Flake8/AST checks
- Explain the debate agents for logic bugs

Slide: Roadmap & Extensions
- Invite collaboration; describe 1-2 next steps

Slide: Q&A
- Be ready for technical deep dive questions: LLM cost, false positives, security

Notes for demo handling
- If Docker Compose isn't available, run unit test that demonstrates patch generation:

```powershell
# Run a unit test locally
python -m pytest tests/test_patch_generator.py::test_generate_patch -q
```

- Have screenshots ready in `grafana/dashboards/neuroci.json` and `tests/fixtures/expected_patches` for fallback
