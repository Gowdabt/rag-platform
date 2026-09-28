# Evaluation (as implemented)

## What exists

`EvalService` (`backend/app/application/eval.py`) plus HTTP under `/api/v1/eval/...`.

- Create/list datasets
- Add items (`question`, optional `expected_answer` / sources)
- Run a dataset: each item calls `ChatService.ask`, stores `EvaluationResult` with lexical F1, citation recall, blended score
- Unit tests: `tests/unit/test_eval_scoring.py`

Metrics today:

- `lexical_f1`
- `citation_recall` (name/id overlap, not chunk-span alignment)
- `answer_contains_expected`
- `score` = mean of F1 and recall

Runs record model/embedding/retriever via the chat path’s normal persistence (`retrieval_events` on the chat message). Dataset runs store per-item metrics on `evaluation_results`.

## What does not exist yet

- Groundedness / hallucination **NLI** scores
- Automatic promotion of user feedback into production prompts
- A checked-in golden regression JSON with CI gates on quality
- Evaluator version field as a first-class column (use git SHA operationally)

## Feedback

`POST /api/v1/messages/{id}/feedback` stores `helpful` / ratings on `message_feedback`. It does **not** auto-tune retrieval or prompts.

## How to run

Use Admin/eval API after logging in, or:

```bash
# after signup, with a bearer token
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/eval/datasets
```

Frontend `evalApi` in `frontend/src/api/client.ts` is wired; there is no dedicated Eval page yet (Admin lists jobs/eval-related stats depending on `admin/stats`).
