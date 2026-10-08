# MVP 接口契约

所有路由前缀 `/api`。日期为带 UTC 时区的 ISO 字符串。错误为 `{detail: "中文说明"}`。ID 为整数，删除返回 204。下列契约用于后端与前端并行实现，最终 OpenAPI 由实际路由生成。

## 卡片和文件夹

- `GET /cards?q=&tag_id=&folder_id=&offset=0&limit=100` → `{items: Card[], total}`。
- `POST /cards`、`PUT /cards/{id}` 输入 `{term, definition, reference_note, tags: string[], folder_ids: number[]}` → Card。
- `GET /cards/{id}` → Card；`DELETE /cards/{id}`。
- Card = `{id,term,definition,reference_note,tags: {id,name}[],folders: {id,name}[],created_at,updated_at}`。
- `GET /tags` → `{id,name,card_count}[]`；`POST /tags`、`PUT /tags/{id}` 输入 `{name}`；`DELETE /tags/{id}`。
- `GET /folders` → Folder[]；`POST /folders`、`PUT /folders/{id}` 输入 `{name}`；`DELETE /folders/{id}`。
- Folder = `{id,name,card_count,created_at}`；删除文件夹不删除卡片。
- `GET /folders/{id}/export` → `[{term,definition,tags:string[],reference_note}]` JSON 下载。
- `POST /imports/preview` 输入 ImportRequest → ImportReport。
- `POST /imports/confirm` 输入 ImportRequest + `preview_token` → ImportReport + `folder_id`。
- ImportRequest = `{content:string,filename?:string,folder_id?:number|null,folder_name?:string,duplicate_mode:'skip'|'overwrite'}`。
- ImportReport = `{added,skipped,overwritten,invalid,rows:[{term,definition,action:'add'|'skip'|'overwrite'|'invalid',reason:string}],preview_token:string}`。新文件夹默认以 filename 去扩展名命名。预览不写库；确认复核 token，变化返回 409。覆盖共享卡片须在 reason 明示。

## 考试与统计

- `POST /exams` 输入 `{folder_id}` → Exam。
- `GET /exams?limit=20` → `{items: Exam[],total}`。
- `GET /exams/{id}` → Exam，答案仅题目、提交状态，不泄露参考定义。
- Exam = `{id,folder_id,folder_name,parent_session_id,started_at,finished_at,total,submitted_count,graded_count,failed_count,pass_threshold,answers: Question[]}`。
- Question = `{id,card_id,position,term,user_answer,time_spent_ms,submitted_at,status}`。
- `POST /answers/{id}/submit` 输入 `{user_answer,time_spent_ms}` → `{accepted:true,answer_id}`；幂等相同提交，不覆盖已提交答案；不等待评分。
- `GET /exams/{id}/results` → Exam，但 answers 为 Answer[]；未全部提交时不允许显示参考答案（409）。
- Answer = Question + `{definition,accuracy,completeness,final_score,merged_feedback,model_knowledge_notes,judges,disagreement,merge_fallback,grading_error,prompt_version,model_name,created_at,error_types:{id,name}[]}`。
- judges = `{judge_index,success,accuracy,completeness,raw_json,raw_text,error}[]`。反馈结构沿用核心契约。
- `POST /exams/{id}/retry` → 新 Exam；只重考已评分且低于本场及格线的题，题干/参考沿用原场快照；未结束或仍有 pending 时 409，没有错题 400。
- `POST /answers/{id}/retry-grade` → `{accepted:true,answer_id}`；仅对已提交的 failed 重试，用原场评分配置和当前匹配提供商的密钥。
- `PATCH /answers/{id}/error-types` 输入 `{error_type_ids:number[]}` → Answer；只允许已评分答案。
- `GET /cards/{id}/history` → `{card:Card,stats:CardStats,answers:Answer[]}`。
- `GET /stats?folder_id=&tag_id=` → `{overview:{card_count,folder_count,attempt_count,graded_count,average_score,average_time_ms},error_distribution:{id,name,count}[],cards:CardStats[],recent_exams:Exam[]}`。
- CardStats = `{id,term,tags:{id,name}[],folder_ids:number[],attempt_count,average_score,lowest_score,last_score,average_time_ms}`；未评分不当作 0；cards 按平均分升序，未评分卡片排后。

## 设置与核对

- `GET /settings` → SettingsData 去掉 api_key，加 has_api_key。
- `PUT /settings` 输入完整配置（api_key 可省略/null 表示保留，空串清除）；返回同 GET。切换 provider/base_url 时若未提供新密钥则清除旧密钥。
- `GET /providers` → `{id,name,base_url,suggested_model}[]`。
- `POST /settings/test` 输入与 PUT 相同但不保存（{} 表示用已保存设置） → `{ok:true,message}`。
- `POST /precheck` 输入 `{term,definition,reference_note}` → PrecheckFeedback，不保存。
- `GET /error-types` → `{id,name}[]`；`POST /error-types`、`PUT /error-types/{id}` 输入 `{name}`；`DELETE /error-types/{id}`。重命名/删除同步现存历史反馈及关系。
- `GET /health` → `{status:'ok',message,phase:4}`。

## 本地后台

create_app(db_path=None, seed=True) 在 lifespan 建立数据库与服务。`app.state.session_factory` 提供 Session；`app.state.grading_service` 可注入模拟服务；`app.state.grading_queue` 后台队列使用 `enqueue(answer_id)` 非阻塞方法，`start()` 恢复遗留 pending，`stop()` 取消任务且保留持久状态供下次恢复。根应用集成。
