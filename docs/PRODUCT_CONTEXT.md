# Role & Objective
You are an expert full-stack developer. Build a **local-only, single-user** web app for memorizing
concept definitions (e.g. ML/DL terms) for exams and interviews: I write term + definition cards
(or import them in bulk), optionally let an AI sanity-check them, then take randomized dictation
exams graded by an LLM, and review per-card score history and error-type statistics.

## Hard Constraints
- Runs entirely on my machine. No deployment, no auth/login, no multi-user, no cloud sync.
  The only network calls are to LLM APIs.
- Backend: Python + FastAPI + SQLite (SQLAlchemy or SQLModel). Frontend: React + Vite + TypeScript.
- FastAPI serves the built React static files, so ONE command (`python run.py`) starts everything
  and opens the browser at http://localhost:<port>. Also provide a dev mode (Vite dev server + proxy).
- UI language: **Simplified Chinese only**. All LLM feedback must be in Simplified Chinese
  (technical terms may keep their English original, e.g. "过拟合 (overfitting)").
- Card content is **plain text** (no Markdown/LaTeX rendering needed).

## 1. Cards
- Fields: term, definition (my reference answer), optional reference note (text I paste from a
  textbook/course to give the AI pre-check extra context), user tags.
- CRUD + search/filter by keyword and user tag.
- **User tags**: free-form, many-to-many with cards, for search and categorization.
- **Folders**: a card can belong to multiple folders (many-to-many).

## 2. Optional AI Pre-check (button on the card edit page)
- Purpose: help me check whether MY reference definition itself is correct. This is the only
  feature where the model uses its own knowledge.
- Sends term + definition (+ reference note if present) to the LLM.
- Returns: correct parts / possibly wrong parts / uncertain parts, up to 3 clarifying questions
  back to me, and an optional suggested rewrite.
- UI shows a disclaimer: "AI 核对结果不一定正确，请自行复查". I decide whether to adopt changes.
- Pre-check results are **NOT stored** in the database.

## 3. Dictation Exam
- Only one direction: show the **term**, I type the **definition** from memory.
- Start an exam from a folder: **all cards in the folder, fully random order**. No spaced repetition.
- Per-question timer (record time spent; no time limit).
- On submit, grading runs **in the background** and I immediately move to the next card.
  The results page at the end shows each question's grading as it completes (polling is fine).
- After the exam: one-click **"只重考错题"** creates a new exam with only the cards scoring below
  the pass threshold (configurable, default 60).

## 4. Grading (multi-judge)
- **The reference definition written by the user is the ONLY grading standard.** Judges must NOT
  use their own knowledge to add or deduct points. Even if the reference definition seems wrong
  or incomplete to the model, grade strictly against it.
- Two dimensions, each 0–100, scored by the LLM (not by code rules):
  - **正确率 (accuracy)**: does what I wrote agree with the reference definition?
    Statements that contradict the reference count as wrong.
  - **完整度 (completeness)**: how many of the reference definition's points did I cover?
- Content in my answer that the reference does not mention: neither add nor deduct points.
  If the model believes such content is factually wrong, it goes into `model_knowledge_notes`,
  not into the score.
- Final score = w_acc * accuracy + w_comp * completeness; weights configurable in Settings
  (default 0.5 / 0.5).
- **Judges**: the same configured model is called N times in parallel (N = 2 or 3, configurable,
  default 3), temperature 0.7 (configurable). Each judge returns JSON:
  `{accuracy, completeness, correct_parts[], wrong_parts[], uncertain_parts[], error_types[],
    model_knowledge_notes[], reasoning}`
- Aggregation: code averages the numeric scores across successful judges; then ONE extra LLM call
  (temperature 0.2) merges the judges' outputs into the final feedback with exactly three graded
  sections: **正确的部分 / 错误的部分 / 不确定的部分** (all relative to the reference definition),
  plus the final error_types list and merged, deduplicated model_knowledge_notes.
- Store each judge's raw scores so I can see disagreement (show a warning if judges differ by >20).
- Validate all LLM JSON with Pydantic; on parse failure retry once; if still failing, mark that
  judge as failed (exclude from average). If all judges fail, mark the answer "未评分" — never
  fabricate a score. If the merge call fails, fall back to showing the first successful judge's
  three sections.

## 4.1 Model Knowledge Notes (not scored)
- Shown in a separate, visually distinct block below the grading result, titled
  "模型提示（不计分，仅供参考）". Typical content:
  - "你的参考定义中 X 的说法可能有误……"
  - "你的回答中提到的 Y（参考定义未涉及）可能不准确……"
- These notes never affect accuracy, completeness, the final score, or error-type labels.
- Store them with the answer so I can review them later and fix my card if needed.

## 5. Error-type Labels
- A fixed, editable list of error types the AI must choose from (judges receive the current list
  in the prompt and may only output names from it). Defaults:
  遗漏要点, 概念错误, 概念混淆, 表述不精确.
- I can add/rename/delete types in Settings, and manually change the error labels on any graded
  answer.
- These are separate from user card tags.

## 6. Statistics
- Per card: attempt count, average score, lowest score, last score, average time spent
  (simple numbers, no "stable/weak" classification).
- Dashboard: error-type distribution (overall and filterable by folder / user tag),
  list of cards sorted by average score ascending, score history per card.
- Clicking a card shows all past answers with their grading and model knowledge notes.

## 7. LLM Providers (BYOK, via LiteLLM)
- Settings page: choose provider, enter API key and model name (free-text with a suggested default
  I can overwrite; never hard-code model versions in logic).
- Presets with base URLs pre-filled: **DeepSeek, Google Gemini, OpenAI, Kimi (Moonshot),
  Qwen (DashScope, OpenAI-compatible mode)**, plus a "Custom OpenAI-compatible" option.
- "测试连接" button.
- Keys stored in local SQLite in plaintext is acceptable (local single-user); mask them in the UI.
- Non-streaming chat completions; request JSON output (use response_format json mode where the
  provider supports it, otherwise instruct via prompt and parse).

## 8. Import Question Bank (JSON)
- One-click import of a `.json` file (file picker or paste JSON text) into a folder: either an
  existing folder or a new folder (default new folder name = file name).
- Accept BOTH formats (auto-detect):
  - Simple object, term → definition:
    ```json
    { "过拟合": "模型在训练集上表现好，但在新数据上泛化差……", "Dropout": "训练时随机丢弃部分神经元……" }
    ```
  - Array of objects (only `term` and `definition` required; `tags` and `reference_note` optional):
    ```json
    [ { "term": "过拟合", "definition": "……", "tags": ["正则化"], "reference_note": "" } ]
    ```
- Encoding: UTF-8 (also handle UTF-8 with BOM). Trim whitespace; skip entries with empty term
  or definition.
- Duplicate handling (same term already in the target folder, compared after trimming,
  case-insensitive): option "跳过" (default) or "覆盖定义".
- Show a preview before confirming (number of cards to add / skip / overwrite, plus the first
  few rows), then an import report (added / skipped / overwritten / invalid with reasons).
- Validate with Pydantic; reject the file with a clear Chinese error message if it is not valid JSON
  or matches neither format.
- Imported cards do NOT trigger AI pre-check automatically.
- Export: a folder can be exported to the same array-of-objects format (for backup/sharing).

## Data Model (minimum)
- cards (id, term, definition, reference_note, created_at, updated_at)
- user_tags, card_user_tags
- folders, card_folders
- exam_sessions (id, folder_id, parent_session_id for "只重考错题", started_at, finished_at)
- exam_answers (id, session_id, card_id, **snapshot of term + definition at exam time**,
  user_answer, time_spent_ms, accuracy, completeness, final_score, merged_feedback JSON,
  model_knowledge_notes JSON, status [pending/graded/failed], prompt_version, model_name,
  created_at)
- judge_results (id, answer_id, judge_index, accuracy, completeness, raw_json, success)
- error_types (id, name), answer_error_types (answer_id, error_type_id)
- settings (single row: provider, base_url, api_key, model, judge_count, judge_temperature,
  merge_temperature, w_accuracy, w_completeness, pass_threshold)

## Output Requirements
1. Project structure (backend/ and frontend/).
2. Full runnable MVP code: models, API routes, LLM service, React pages
   (卡片管理, 文件夹, 导入题库, 考试, 考试结果, 统计看板, 设置). Do not omit files or write
   "rest of the code here" placeholders.
3. All LLM prompts (pre-check, judge, merge) in a single `backend/prompts.py`, with a
   `PROMPT_VERSION` constant.
4. requirements.txt, package.json, README with setup and run commands, and an example import file
   `examples/ml_terms.json`.
5. Seed data: ~10 ML concept cards (e.g. 过拟合, 梯度消失, Dropout, BatchNorm, 交叉熵…) in one folder.

## Delivery in Phases
Deliver in the phases below. After each phase, stop and wait for my confirmation before continuing.
Keep the schema and API contract consistent across phases; if a change is needed, state it explicitly.
1. **Backend core**: project structure, database models, settings, LLM service (LiteLLM,
   multi-judge grading, merge), `prompts.py`, and a CLI script to grade one sample answer against
   a real model.
2. **Backend API**: routes for cards, tags, folders, JSON import/export, exams (with background
   grading), statistics, error types, settings; pytest tests with the LLM mocked (include import
   tests for both formats, duplicates, and invalid files). List the final API endpoints.
3. **Frontend**: React pages calling the API from phase 2 (generate TS types from FastAPI's OpenAPI
   schema if possible).
4. **Finish**: "只重考错题", seed data, example import file, `run.py` one-command start, README.