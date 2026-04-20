# Walker DevOps — Launch Planning Agent App

Walker DevOps is a full-stack launch-planning app built with the OpenAI Agents SDK. It takes a product brief and outputs an actionable launch plan with priorities, risks, owner checklists, copy suggestions, and follow-up questions.

## Stack

- **Frontend:** React + Vite (`frontend/`)
- **Backend API:** Express (`server/`)
- **Agent runtime:** OpenAI Agents SDK (`agent/`)
- **Tests:** Vitest (`tests/`)
- **Streaming verification:** scripted SSE check (`scripts/verify-stream.ts`)

## Project structure

```text
projects/app/walker_devops/
  agent/
    launchPlannerAgent.ts
    tools.ts
    types.ts
  server/
    index.ts
    routes/launch.ts
  frontend/
    src/
      components/
      lib/
      App.tsx
      main.tsx
      styles.css
  scripts/
    verify-stream.ts
  tests/
    tools.test.ts
  .env.example
  README.md
```

## Agent behavior

The agent is configured to always deliver:

1. Prioritized launch plan
2. Risk register
3. Owner checklist
4. Channel-specific launch copy suggestions
5. Follow-up questions for missing details

Tool patterns included:

- `extract_launch_tasks`
- `check_launch_readiness`
- `generate_owner_checklist`
- `draft_launch_copy`
- `create_risk_register`

## Setup

1. Copy environment template:
   ```bash
   cp .env.example .env
   ```
2. Set your OpenAI key in `.env`:
   ```bash
   OPENAI_API_KEY=sk-...
   ```
3. Install dependencies:
   ```bash
   npm install
   ```
4. Start both servers:
   ```bash
   npm run dev
   ```

- Frontend: `http://localhost:5174`
- API: `http://localhost:8787`

## Local verification checklist

### Agent behavior
- [ ] Agent returns prioritized plan with owner + rationale fields.
- [ ] Agent returns a risk register with mitigation owners.
- [ ] Agent adds follow-up questions when details are missing.

### Frontend flow
- [ ] Form accepts brief, audience, launch date, constraints, assets.
- [ ] UI streams progressive text updates while tools run.
- [ ] UI displays tool progress events.

### Tool outputs
- [ ] Task extraction returns P0/P1/P2 priorities.
- [ ] Readiness checker returns score + per-rubric checks.
- [ ] Owner checklist groups by PM/Engineering/Marketing/Support.
- [ ] Launch copy returns email/social/in-app/release notes variants.

### End-to-end streamed API verification (required)
Run this **after** the server starts and `OPENAI_API_KEY` is configured:

```bash
npm run verify:stream
```

Expected outcome:
- At least one `tool_event` in the stream
- At least one `text_delta` in the stream

## Tracing / observability

- Tracing follows OpenAI Agents SDK defaults.
- To disable tracing for local testing:
  ```bash
  OPENAI_AGENTS_DISABLE_TRACING=1
  ```

## Extending tools or handoffs

- Add new tools in `agent/tools.ts`.
- Register tools in `agent/launchPlannerAgent.ts`.
- Update stream rendering rules in `server/routes/launch.ts` and `frontend/src/lib/streamClient.ts`.
