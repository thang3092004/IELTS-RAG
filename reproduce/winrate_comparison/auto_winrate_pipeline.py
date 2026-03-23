import argparse
import json
import os
import time
from pathlib import Path
from typing import Literal

import tiktoken
from openai import OpenAI
from openai.lib._parsing._completions import type_to_response_format_param
from pydantic import BaseModel, Field


OPENAI_API_KEY = ""
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY


def ensure_api_key():
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("Please set OPENAI_API_KEY (hardcoded or environment variable) before running this script.")


class Criterion(BaseModel):
    Winner: Literal["Answer 1", "Answer 2"]
    Explanation: str


class Result(BaseModel):
    Comprehensiveness: Criterion
    Empowerment: Criterion
    Trustworthiness: Criterion
    Depth: Criterion
    Density: Criterion
    Overall_Winner: Criterion = Field(alias="Overall Winner")


sys_prompt = """
You are an expert tasked with evaluating two answers to the same question based on these criteria: **Comprehensiveness**, **Empowerment**, **Trustworthiness**, **Depth** and **Density**.
"""

prompt = """
You will evaluate two answers to the same question based on these criteria: **Comprehensiveness**, **Empowerment**, **Trustworthiness**, **Depth** and **Density**.

For each criterion, choose the better answer (either Answer 1 or Answer 2) and explain why. Then, select an overall winner based on these criteria.

Here is the question:
{query}

Here are the two answers:

**Answer 1:**
{answer1}

**Answer 2:**
{answer2}

Evaluate both answers using the criteria listed above and provide detailed explanations for each criterion.

Output your evaluation in the following JSON format:

{{
    "Comprehensiveness": {{
        "Winner": "[Answer 1 or Answer 2]",
        "Explanation": "[Provide explanation here]"
    }},
    "Empowerment": {{
        "Winner": "[Answer 1 or Answer 2]",
        "Explanation": "[Provide explanation here]"
    }},
    "Trustworthiness": {{
        "Winner": "[Answer 1 or Answer 2]",
        "Explanation": "[Provide explanation here]"
    }},
    "Depth": {{
        "Winner": "[Answer 1 or Answer 2]",
        "Explanation": "[Provide explanation here]"
    }},
    "Density": {{
        "Winner": "[Answer 1 or Answer 2]",
        "Explanation": "[Provide explanation here]"
    }},
    "Overall Winner": {{
        "Winner": "[Answer 1 or Answer 2]",
        "Explanation": "[Summarize why this answer is the overall winner on the above criteria]"
    }}
}}
"""


TERMINAL_BATCH_STATES = {"completed", "failed", "cancelled", "expired"}
ACTIVE_BATCH_STATES = {"validating", "in_progress", "finalizing"}
THROTTLE_KEYWORDS = ["token_limit_exceeded", "enqueued", "limit", "quota", "rate"]


def check_response_valid(data):
    valid_keys = ["Comprehensiveness", "Empowerment", "Trustworthiness", "Depth", "Density", "Overall Winner"]
    if len(data) != 6:
        return False
    if set(list(data.keys())) != set(valid_keys):
        return False
    for key in valid_keys:
        if data[key]["Winner"] not in ["Answer 1", "Answer 2"]:
            return False
        if "Explanation" not in list(data[key].keys()):
            return False
    return True


def build_requests(dataset_path: Path, answers_root: Path):
    with open(dataset_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    encoding = tiktoken.encoding_for_model("gpt-4o-mini")
    response_format = type_to_response_format_param(Result)

    our_answer_dir = "answers-videorag"
    com_answer_dir = [
        "answers-naiverag",
        "answers-graphrag-local",
        "answers-graphrag-global",
        "answers-lightrag-hybrid",
    ]

    requests = []
    request_token_counts = []

    for _id in questions:
        video_list_name = questions[_id][0]["description"]
        data_path = answers_root / f"{_id}-{video_list_name}"
        for compare_dir in com_answer_dir:
            our_work_dir = data_path / our_answer_dir
            com_work_dir = data_path / compare_dir
            for i in range(len(questions[_id][0]["questions"])):
                query_id = questions[_id][0]["questions"][i]["id"]
                query = questions[_id][0]["questions"][i]["question"]

                our_answer = (our_work_dir / f"answer_{query_id}.md").read_text(encoding="utf-8")
                com_answer = (com_work_dir / f"answer_{query_id}.md").read_text(encoding="utf-8")

                ori_prompt = prompt.format(query=query, answer1=our_answer, answer2=com_answer)
                rev_prompt = prompt.format(query=query, answer1=com_answer, answer2=our_answer)

                ori_request_data = {
                    "custom_id": f"{_id}-{video_list_name}++query{query_id}++{our_answer_dir}++{compare_dir}++ori",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": ori_prompt},
                        ],
                        "response_format": response_format,
                    },
                }
                rev_request_data = {
                    "custom_id": f"{_id}-{video_list_name}++query{query_id}++{compare_dir}++{our_answer_dir}++rev",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": rev_prompt},
                        ],
                        "response_format": response_format,
                    },
                }

                ori_token_count = len(encoding.encode(ori_prompt))
                rev_token_count = len(encoding.encode(rev_prompt))

                requests.append(ori_request_data)
                request_token_counts.append(ori_token_count)
                requests.append(rev_request_data)
                request_token_counts.append(rev_token_count)

    return requests, request_token_counts


def split_requests(requests, token_counts, max_tokens):
    chunks = []
    token_chunks = []

    current_chunk = []
    current_tokens = 0

    for request, token_count in zip(requests, token_counts):
        if current_chunk and current_tokens + token_count > max_tokens:
            chunks.append(current_chunk)
            token_chunks.append(current_tokens)
            current_chunk = []
            current_tokens = 0
        current_chunk.append(request)
        current_tokens += token_count

    if current_chunk:
        chunks.append(current_chunk)
        token_chunks.append(current_tokens)

    return chunks, token_chunks


def write_jsonl(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def parse_jsonl_request_file(request_json_path: Path):
    request_dict = {}
    with open(request_json_path, "r", encoding="utf-8") as f:
        for line in f:
            json_data = json.loads(line)
            request_dict[json_data["custom_id"]] = {
                "model": json_data["body"]["model"],
                "messages": json_data["body"]["messages"],
                "response_format": json_data["body"]["response_format"],
            }
    return request_dict


def download_output_json(client: OpenAI, output_file_id: str, output_path: Path):
    content = client.files.content(output_file_id).content
    temp_path = output_path.with_suffix(".temp")
    with open(temp_path, "wb") as f:
        f.write(content)

    results = []
    with open(temp_path, "r", encoding="utf-8") as f:
        for line in f:
            results.append(json.loads(line.strip()))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    temp_path.unlink(missing_ok=True)


def parse_results(results_json_path: Path, request_json_path: Path, parsed_output_path: Path, retry_limit: int = 6):
    with open(results_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    request_dict = parse_jsonl_request_file(request_json_path)
    client = OpenAI()
    parsed = {}

    for i, item in enumerate(data):
        custom_id = item.get("custom_id")
        try:
            json_data = json.loads(item["response"]["body"]["choices"][0]["message"]["content"])
            if not check_response_valid(json_data):
                raise ValueError("Invalid response schema")
            parsed[custom_id] = json_data
        except Exception:
            if custom_id not in request_dict:
                continue
            retries = 0
            while retries < retry_limit:
                try:
                    response = client.chat.completions.create(
                        model=request_dict[custom_id]["model"],
                        messages=request_dict[custom_id]["messages"],
                        response_format=request_dict[custom_id]["response_format"],
                    )
                    json_data = json.loads(response.choices[0].message.content)
                    if check_response_valid(json_data):
                        parsed[custom_id] = json_data
                        break
                except Exception:
                    time.sleep(1)
                retries += 1
        if (i + 1) % 100 == 0:
            print(f"parsed {i + 1}/{len(data)} rows from {results_json_path.name}")

    with open(parsed_output_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=4, ensure_ascii=False)


def key_of(run_idx: int, part_idx: int):
    return f"{run_idx}:{part_idx}"


def save_manifest(manifest_path: Path, manifest):
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def load_manifest(manifest_path: Path):
    if not manifest_path.exists():
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def status_is_done(task):
    return bool(task.get("parsed_file")) and task.get("status") == "completed"


def is_selected(task, submit_run, submit_part):
    if submit_run is not None and task["run"] != submit_run:
        return False
    if submit_part is not None and task["part"] != submit_part:
        return False
    return True


def reset_workspace(base_dir: Path):
    patterns = [
        "auto_run*_part*.json",
        "auto_manifest_*.json",
        "auto_manifest_latest.json",
        "file-*.json",
        "file-*.temp",
    ]
    deleted = 0
    for pattern in patterns:
        for path in base_dir.glob(pattern):
            if path.is_file():
                path.unlink(missing_ok=True)
                deleted += 1
    return deleted


def build_initial_tasks(base_dir: Path, run_time: int, chunks, token_chunks):
    tasks = {}
    for run_idx in range(run_time):
        for part_idx, (chunk, chunk_tokens) in enumerate(zip(chunks, token_chunks)):
            request_file = base_dir / f"auto_run{run_idx}_part{part_idx}.json"
            if not request_file.exists():
                write_jsonl(request_file, chunk)

            task = {
                "run": run_idx,
                "part": part_idx,
                "key": key_of(run_idx, part_idx),
                "request_file": request_file.name,
                "tokens": chunk_tokens,
                "batch_id": None,
                "batch_input_file_id": None,
                "status": "pending",
                "output_file_id": None,
                "results_file": None,
                "parsed_file": None,
                "last_completed": 0,
                "last_total": 0,
                "poll_delay": 2,
                "next_poll_at": 0,
                "submit_attempts": 0,
                "error": None,
            }
            tasks[task["key"]] = task
    return tasks


def merge_manifest_tasks(tasks, old_manifest):
    if not old_manifest:
        return
    for old_task in old_manifest.get("tasks", []):
        key = old_task.get("key")
        if key in tasks:
            tasks[key].update(old_task)


def submit_task(client: OpenAI, task, base_dir: Path):
    request_file = base_dir / task["request_file"]
    with open(request_file, "rb") as f:
        batch_input_file = client.files.create(file=f, purpose="batch")
    batch = client.batches.create(
        input_file_id=batch_input_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"description": f"auto runtime{task['run']}-part{task['part']}: {task['request_file']}"},
    )
    now = time.time()
    task["batch_id"] = batch.id
    task["batch_input_file_id"] = batch_input_file.id
    task["status"] = batch.status
    task["next_poll_at"] = now
    task["poll_delay"] = 2
    task["submit_attempts"] = task.get("submit_attempts", 0) + 1
    task["error"] = None
    print(f"submitted key={task['key']} batch={batch.id} tokens~{task['tokens']}")


def compute_next_poll_delay(task, min_poll_seconds: int, max_poll_seconds: int, progress_changed: bool):
    if progress_changed:
        return min_poll_seconds
    current = int(task.get("poll_delay", min_poll_seconds))
    return min(max_poll_seconds, max(min_poll_seconds, current * 2))


def ensure_download_and_parse(client: OpenAI, task, base_dir: Path):
    if task.get("status") != "completed" or not task.get("output_file_id"):
        return

    results_file = base_dir / f"{task['output_file_id']}.json"
    parsed_file = base_dir / f"{task['output_file_id']}-parse-result.json"
    request_file = base_dir / task["request_file"]

    if not results_file.exists():
        download_output_json(client, task["output_file_id"], results_file)
        print(f"downloaded key={task['key']} file={results_file.name}")
    task["results_file"] = results_file.name

    if not parsed_file.exists():
        parse_results(results_file, request_file, parsed_file)
        print(f"parsed key={task['key']} file={parsed_file.name}")
    task["parsed_file"] = parsed_file.name


def poll_task(client: OpenAI, task, min_poll_seconds: int, max_poll_seconds: int):
    now = time.time()
    if now < float(task.get("next_poll_at", 0)):
        return False

    batch_obj = client.batches.retrieve(task["batch_id"])
    completed = batch_obj.request_counts.completed if batch_obj.request_counts else 0
    total = batch_obj.request_counts.total if batch_obj.request_counts else 0
    prev_completed = int(task.get("last_completed", 0))
    prev_status = task.get("status")

    task["status"] = batch_obj.status
    task["output_file_id"] = batch_obj.output_file_id
    task["last_completed"] = completed
    task["last_total"] = total

    progress_changed = completed > prev_completed or batch_obj.status != prev_status
    if batch_obj.status in TERMINAL_BATCH_STATES:
        task["poll_delay"] = min_poll_seconds
        task["next_poll_at"] = now
    else:
        delay = compute_next_poll_delay(task, min_poll_seconds, max_poll_seconds, progress_changed)
        task["poll_delay"] = delay
        task["next_poll_at"] = now + delay

    print(
        f"poll key={task['key']} batch={task['batch_id']} status={batch_obj.status} "
        f"progress={completed}/{total} next_poll={int(task['poll_delay'])}s"
    )
    return True


def summarize(tasks, selected_keys):
    selected = [tasks[k] for k in selected_keys]
    counts = {
        "pending": 0,
        "active": 0,
        "completed_no_parse": 0,
        "parsed": 0,
        "failed": 0,
    }
    for task in selected:
        if status_is_done(task):
            counts["parsed"] += 1
        elif task.get("status") in ACTIVE_BATCH_STATES:
            counts["active"] += 1
        elif task.get("status") == "completed":
            counts["completed_no_parse"] += 1
        elif task.get("status") in {"failed", "cancelled", "expired"}:
            counts["failed"] += 1
        else:
            counts["pending"] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description="High-throughput winrate pipeline with adaptive polling and resume")
    parser.add_argument("--run-time", type=int, default=5)
    parser.add_argument("--max-enqueued-tokens", type=int, default=300000)
    parser.add_argument("--submit-run", type=int, default=None)
    parser.add_argument("--submit-part", type=int, default=None)
    parser.add_argument("--min-poll-seconds", type=int, default=2)
    parser.add_argument("--max-poll-seconds", type=int, default=20)
    parser.add_argument("--heartbeat-seconds", type=int, default=15)
    parser.add_argument("--max-concurrent-batches", type=int, default=8)
    parser.add_argument("--submit-cooldown-seconds", type=int, default=8)
    parser.add_argument("--retry-failed-submit", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true", help="Delete current auto artifacts before starting")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir / "batch_requests" / "overall_comparison_rag"
    base_dir.mkdir(parents=True, exist_ok=True)

    if args.reset:
        deleted = reset_workspace(base_dir)
        print(f"reset=true deleted_files={deleted}")

    dataset_path = script_dir.parent.parent / "longervideos" / "dataset.json"
    answers_root = script_dir.parent / "all_answers"

    requests, token_counts = build_requests(dataset_path, answers_root)
    chunks, token_chunks = split_requests(requests, token_counts, args.max_enqueued_tokens)

    print(f"Total requests: {len(requests)}")
    print(f"Split into {len(chunks)} part(s), max tokens per part: {args.max_enqueued_tokens}")

    tasks = build_initial_tasks(base_dir, args.run_time, chunks, token_chunks)
    manifest_path = base_dir / "auto_manifest_latest.json"
    old_manifest = load_manifest(manifest_path)
    merge_manifest_tasks(tasks, old_manifest)

    selected_keys = [k for k, t in tasks.items() if is_selected(t, args.submit_run, args.submit_part)]
    selected_keys.sort(key=lambda k: (tasks[k]["run"], tasks[k]["part"]))
    if not selected_keys:
        raise ValueError("No tasks selected. Check --submit-run/--submit-part")

    if args.dry_run:
        print(f"dry_run=true selected_tasks={len(selected_keys)}")
        return

    ensure_api_key()
    client = OpenAI()
    last_heartbeat = 0.0
    next_submit_at = 0.0

    while True:
        now = time.time()
        all_done = all(status_is_done(tasks[k]) for k in selected_keys)
        if all_done:
            break

        inflight_tokens = 0
        active_count = 0
        for key in selected_keys:
            task = tasks[key]
            if task.get("batch_id") and task.get("status") in ACTIVE_BATCH_STATES:
                inflight_tokens += int(task.get("tokens", 0))
                active_count += 1

        for key in selected_keys:
            task = tasks[key]
            if task.get("status") == "completed":
                ensure_download_and_parse(client, task, base_dir)

        save_manifest(
            manifest_path,
            {
                "updated_at": int(time.time()),
                "run_time": args.run_time,
                "max_enqueued_tokens": args.max_enqueued_tokens,
                "selected": {"submit_run": args.submit_run, "submit_part": args.submit_part},
                "tasks": [tasks[k] for k in sorted(tasks.keys(), key=lambda x: (tasks[x]["run"], tasks[x]["part"]))],
            },
        )

        for key in selected_keys:
            task = tasks[key]
            if task.get("batch_id") and task.get("status") in ACTIVE_BATCH_STATES:
                poll_task(client, task, args.min_poll_seconds, args.max_poll_seconds)
                if task.get("status") in TERMINAL_BATCH_STATES:
                    ensure_download_and_parse(client, task, base_dir)

        inflight_tokens = 0
        active_count = 0
        for key in selected_keys:
            task = tasks[key]
            if task.get("batch_id") and task.get("status") in ACTIVE_BATCH_STATES:
                inflight_tokens += int(task.get("tokens", 0))
                active_count += 1

        if now >= next_submit_at:
            for key in selected_keys:
                task = tasks[key]

                if status_is_done(task):
                    continue

                if task.get("status") in {"failed", "cancelled", "expired"} and task.get("submit_attempts", 0) >= args.retry_failed_submit:
                    continue

                if task.get("batch_id") and task.get("status") in ACTIVE_BATCH_STATES:
                    continue

                if task.get("status") == "completed":
                    continue

                if active_count >= args.max_concurrent_batches:
                    break
                if inflight_tokens + int(task.get("tokens", 0)) > args.max_enqueued_tokens:
                    continue

                try:
                    submit_task(client, task, base_dir)
                    inflight_tokens += int(task.get("tokens", 0))
                    active_count += 1
                except Exception as e:
                    message = str(e)
                    task["error"] = message
                    lower_message = message.lower()
                    if any(keyword in lower_message for keyword in THROTTLE_KEYWORDS):
                        next_submit_at = time.time() + max(1, args.submit_cooldown_seconds)
                        print(f"submit_throttled wait={args.submit_cooldown_seconds}s reason={message}")
                        break
                    task["status"] = "failed"
                    task["submit_attempts"] = task.get("submit_attempts", 0) + 1
                    if task["submit_attempts"] < args.retry_failed_submit:
                        task["status"] = "pending"
                        print(f"submit_failed_retry key={task['key']} attempt={task['submit_attempts']} err={message}")
                    else:
                        print(f"submit_failed_final key={task['key']} err={message}")

        if time.time() - last_heartbeat >= max(1, args.heartbeat_seconds):
            summary = summarize(tasks, selected_keys)
            print(
                f"heartbeat pending={summary['pending']} active={summary['active']} "
                f"completed_no_parse={summary['completed_no_parse']} parsed={summary['parsed']} failed={summary['failed']}"
            )
            last_heartbeat = time.time()

        sleep_seconds = 1
        soonest_poll = None
        for key in selected_keys:
            task = tasks[key]
            if task.get("batch_id") and task.get("status") in ACTIVE_BATCH_STATES:
                next_poll_at = float(task.get("next_poll_at", time.time() + 1))
                if soonest_poll is None or next_poll_at < soonest_poll:
                    soonest_poll = next_poll_at

        if soonest_poll is not None:
            sleep_seconds = max(0.2, min(1.5, soonest_poll - time.time()))
        time.sleep(sleep_seconds)

    final_manifest_ts = int(time.time())
    final_manifest = base_dir / f"auto_manifest_{final_manifest_ts}.json"
    save_manifest(
        final_manifest,
        {
            "updated_at": final_manifest_ts,
            "run_time": args.run_time,
            "max_enqueued_tokens": args.max_enqueued_tokens,
            "selected": {"submit_run": args.submit_run, "submit_part": args.submit_part},
            "tasks": [tasks[k] for k in sorted(tasks.keys(), key=lambda x: (tasks[x]["run"], tasks[x]["part"]))],
        },
    )
    save_manifest(
        manifest_path,
        {
            "updated_at": final_manifest_ts,
            "run_time": args.run_time,
            "max_enqueued_tokens": args.max_enqueued_tokens,
            "selected": {"submit_run": args.submit_run, "submit_part": args.submit_part},
            "tasks": [tasks[k] for k in sorted(tasks.keys(), key=lambda x: (tasks[x]["run"], tasks[x]["part"]))],
        },
    )

    summary = summarize(tasks, selected_keys)
    print(
        f"done pending={summary['pending']} active={summary['active']} "
        f"completed_no_parse={summary['completed_no_parse']} parsed={summary['parsed']} failed={summary['failed']}"
    )
    print(f"manifest_latest={manifest_path.name}")
    print(f"manifest_snapshot={final_manifest.name}")


if __name__ == "__main__":
    main()
