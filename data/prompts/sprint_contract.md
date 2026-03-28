Given this plan:
Goal: {goal}

Steps:
{steps}

Generate testable success criteria for each step. Each criterion should be:
1. Specific and measurable
2. Verifiable without asking the user
3. Based on observable outcomes (file created, data returned, etc.)

Respond with JSON:
{{"criteria": [{{"step": 1, "test": "how to verify this step succeeded", "metric": "measurable outcome"}}], "overall_success": "what does complete success look like"}}