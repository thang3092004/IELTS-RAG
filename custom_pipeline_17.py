import os
import json
import asyncio
import tqdm
import numpy as np
from openai import AsyncOpenAI
from videorag.videorag import VideoRAG, QueryParam
from videorag._llm import openai_4o_mini_config
from dotenv import load_dotenv

load_dotenv()

# --- Sync with official reproduction prompts ---
SYS_PROMPT = """
---Role---
You are an expert evaluating an answer against a baseline answer based on these criteria: **Comprehensiveness**, **Empowerment**, **Trustworthiness**, **Depth** and **Density**.
"""

USER_PROMPT_TEMPLATE = """
You are an expert evaluating an answer against a baseline answer based on these criteria: **Comprehensiveness**, **Empowerment**, **Trustworthiness**, **Depth** and **Density**.

- **Comprehensiveness**: How much detail does the answer provide to cover all aspects and details of the question?
- **Empowerment**: How well does the answer help the reader understand and make informed judgments about the topic?
- **Trustworthiness**: Does the answer provide sufficient detail and align with common knowledge, enhancing its credibility?
- **Depth**: Does the answer provide in-depth analysis or details, rather than just superficial information?
- **Density**: Does the answer contain relevant information without less informative or redundant content?

For the evaluated answer labeled "Evaluation Answer," assign a score from 1 to 5 for each criterion compared to the baseline answer labeled "Baseline Answer." Then, assign an overall score based on these criteria.
The evaluation scores are defined as follows:
- 1: Strongly worse than the baseline answer
- 2: Weakly worse than the baseline answer
- 3: Moderate compared to the baseline answer
- 4: Weakly better than the baseline answer
- 5: Strongly better than the baseline answer

Here is the question:
{query}

Here are the answers:

**Baseline Answer (NaiveRAG):**
{baseline_answer}

**Evaluation Answer ({eval_model_name}):**
{evaluation_answer}

Evaluate the answer using the criteria listed above and provide detailed explanations for the scores.

Output your evaluation in the following JSON format:

{{
    "Comprehensiveness": {{
        "Score": [1 - 5],
        "Explanation": "[Provide explanation here]"
    }},
    "Empowerment": {{
        "Score": [1 - 5],
        "Explanation": "[Provide explanation here]"
    }},
    "Trustworthiness": {{
        "Score": [1 - 5],
        "Explanation": "[Provide explanation here]"
    }},
    "Depth": {{
        "Score": [1 - 5],
        "Explanation": "[Provide explanation here]"
    }},
    "Density": {{
        "Score": [1 - 5],
        "Explanation": "[Provide explanation here]"
    }},
    "Overall Score": {{
        "Score": [1 - 5],
        "Explanation": "[Provide explanation here]"
    }}
}}
"""

async def call_judge(client, sem, task_id, prompt_text):
    async with sem:
        for attempt in range(10):
            try:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYS_PROMPT},
                        {"role": "user", "content": prompt_text},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0
                )
                return task_id, json.loads(response.choices[0].message.content), None
            except Exception as e:
                err_str = str(e)
                wait_time = (attempt + 1) * 20
                if "429" in err_str:
                    await asyncio.sleep(wait_time)
                else:
                    await asyncio.sleep(5)
        return task_id, None, f"Failed {task_id} after 10 attempts"

async def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("Vui lòng cấu hình OPENAI_API_KEY!")
        return

    base_out_dir = "custom_eval_results_17"
    eval_models = {"ieltsrag": "answers-ieltsrag", "videorag": "answers-videorag"}
    out_path = f"{base_out_dir}/judge_output.json"

    judgments_dict = {}
    if os.path.exists(out_path):
        with open(out_path, "r") as f:
            try:
                judgments_dict = json.load(f)
                print(f"Đã tải {len(judgments_dict)} kết quả cũ. Đang tiếp tục...")
            except: pass

    with open("longervideos/dataset.json", "r", encoding="utf-8") as f:
        dataset = json.load(f)
    
    collection_id = "17"
    collection_data = dataset.get(collection_id, [None])[0]
    category_name = f"{collection_id}-{collection_data['description']}"
    questions = collection_data.get("questions", [])
    naive_base_path = f"reproduce/all_answers/{category_name}/answers-naiverag"
    
    client = AsyncOpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None)
    sem = asyncio.Semaphore(1)
    
    tasks = []
    for q in questions:
        q_id = q["id"]
        q_text = q["question"]
        naive_file = f"{naive_base_path}/answer_{q_id}.md"
        if not os.path.exists(naive_file): continue
        with open(naive_file, "r") as f: base_ans = f.read()
            
        for model_key, folder in eval_models.items():
            custom_id = f"{category_name}++query{q_id}++base++answers-naiverag++evaluate++answers-{model_key}"
            if custom_id in judgments_dict: continue

            eval_file = f"{base_out_dir}/{folder}/answer_{q_id}.md"
            if not os.path.exists(eval_file): continue
            with open(eval_file, "r") as f: eval_ans = f.read()
            
            prompt = USER_PROMPT_TEMPLATE.format(
                query=q_text, 
                baseline_answer=base_ans, 
                evaluation_answer=eval_ans,
                eval_model_name=model_key.upper()
            )
            tasks.append(call_judge(client, sem, custom_id, prompt))
        
    if tasks:
        for coro in tqdm.tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Đang chấm thi"):
            task_id, res, err = await coro
            if not err:
                judgments_dict[task_id] = res
                with open(out_path, "w") as f:
                    json.dump(judgments_dict, f, indent=4, ensure_ascii=False)
            else:
                print(f"\n⚠️ {err}")

    metrics = ['Comprehensiveness', 'Empowerment', 'Trustworthiness', 'Depth', 'Density', 'Overall Score']
    summaries = {m: {mk: [] for mk in eval_models} for m in metrics}
    
    total_count = 0
    for task_id, res in judgments_dict.items():
        # Phân loại theo model
        for mk in eval_models:
            if f"++answers-{mk}" in task_id:
                total_count += 1
                for m in metrics:
                    val = res.get(m, {}).get("Score")
                    if val is not None: summaries[m][mk].append(float(val))

    print("\n" + "="*70)
    print(f"KẾT QUẢ ĐÁNH GIÁ TỔNG HỢP (Tổng cộng {len(judgments_dict)} cặp đã chấm)")
    print("="*70)
    for m in metrics:
        scores_line = []
        for mk in eval_models:
            count = len(summaries[m][mk])
            avg = np.mean(summaries[m][mk]) if count > 0 else 0
            scores_line.append(f"{mk.upper()}: {avg:.3f} (n={count})")
        print(f" - {m.ljust(20)}: {' | '.join(scores_line)}")
    
    print(f"\n✅ File kết quả chuẩn đã lưu tại: {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
