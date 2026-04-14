import os
import json
import asyncio
import tqdm
from openai import AsyncOpenAI

# ===========================================================================
# IELTS-RAG Comparison Battle (Real-time Evaluation)
# USES 100% ORIGINAL SYS_PROMPT AND USER_PROMPT_TEMPLATE FROM THE BENCHMARK
# ===========================================================================

SYS_PROMPT = """You are an expert evaluating an answer against a baseline answer based on these criteria: **Comprehensiveness**, **Empowerment**, **Trustworthiness**, **Depth** and **Density**."""

# NGUYÊN BẢN 100% (KHÔNG TÓM TẮT MỘT CHỮ NÀO)
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

**Baseline Answer:**
{baseline_answer}

**Evaluation Answer:**
{evaluation_answer}

Evaluate the answer using the criteria listed above and provide detailed explanations for the scores.

Output your evaluation in the following JSON format:

{{
    "Comprehensiveness": {{
        "Score": "[1 - 5]",
        "Explanation": "[Provide explanation here]"
    }},
    "Empowerment": {{
        "Score": "[1 - 5]",
        "Explanation": "[Provide explanation here]"
    }},
    "Trustworthiness": {{
        "Score": "[1 - 5]",
        "Explanation": "[Provide explanation here]"
    }},
    "Depth": {{
        "Score": "[1 - 5]",
        "Explanation": "[Provide explanation here]"
    }},
    "Density": {{
        "Score": "[1 - 5]",
        "Explanation": "[Provide explanation here]"
    }},
    "Overall Score": {{
        "Score": "[1 - 5]",
        "Explanation": "[Provide explanation here]"
    }}
}}
"""

async def call_judge(client, sem, req):
    async with sem:
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYS_PROMPT},
                    {"role": "user", "content": req["prompt"]},
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            return {
                "method": req["method"],
                "scores": json.loads(resp.choices[0].message.content)
            }
        except Exception as e:
            return None

async def main():
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(15) 
    
    with open('../../longervideos/dataset.json', 'r') as f:
        dataset = json.load(f)
    
    methods = ['answers-videorag', 'answers-ielts-rag']
    ids = ['0', '13', '17']
    tasks = []

    for _id in ids:
        col = dataset[_id][0]
        desc = col['description']
        for q in col['questions']:
            bp = f"../all_answers/{_id}-{desc}/answers-naiverag/answer_{q['id']}.md"
            if not os.path.exists(bp): continue
            with open(bp, 'r') as f: btxt = f.read()
            
            for m in methods:
                tp = f"../all_answers/{_id}-{desc}/{m}/answer_{q['id']}.md"
                if os.path.exists(tp):
                    with open(tp, 'r') as f: ttxt = f.read()
                    prompt = USER_PROMPT_TEMPLATE.format(
                        query=q['question'],
                        baseline_answer=btxt,
                        evaluation_answer=ttxt
                    )
                    tasks.append(call_judge(client, sem, {"method": m, "prompt": prompt}))

    print(f"--- Bắt đầu cuộc So Găng Chuẩn Baseline: {len(tasks)} cặp câu hỏi ---")
    results = [r for r in [await f for f in tqdm.tqdm(asyncio.as_completed(tasks), total=len(tasks))] if r]
    
    # Parse results with flexible key matching
    m_map = {
        'Comprehensiveness': ['Comprehensiveness'],
        'Empowerment': ['Empowerment'],
        'Trustworthiness': ['Trustworthiness'],
        'Depth': ['Depth'],
        'Density': ['Density'],
        'Overall Score': ['Overall Score', 'Overall_Score', 'overall_score', 'Overall score']
    }

    fs = {m: {met: [] for met in m_map} for m in methods}
    for r in results:
        for fname, vars in m_map.items():
            val = 3.0
            found = False
            for v in vars:
                if v in r['scores']:
                    s_data = r['scores'][v]
                    if isinstance(s_data, dict):
                        val = s_data.get('Score', 3.0)
                    else:
                        val = s_data
                    found = True
                    break
            # Force numeric float
            try:
                fs[r['method']][fname].append(float(val))
            except:
                fs[r['method']][fname].append(3.0)

    print("\n" + "="*75)
    print(f"{'TIÊU CHÍ (XỊN)':<25} | {'VideoRAG (Gốc)':<22} | {'IELTS-RAG (Ours)':<22}")
    print("-" * 75)
    for met in m_map:
        v_list = fs['answers-videorag'][met]
        i_list = fs['answers-ielts-rag'][met]
        
        v_avg = sum(v_list)/len(v_list) if v_list else 0
        i_avg = sum(i_list)/len(i_list) if i_list else 0
        diff = i_avg - v_avg
        print(f"{met:<25} | {v_avg:^22.2f} | {i_avg:^22.2f} ({'+' if diff>0 else ''}{diff:.2f})")
    print("="*75)

if __name__ == '__main__':
    asyncio.run(main())
