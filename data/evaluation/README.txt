Saral recruiter benchmark evaluation

Ranking rubric
The live VerificationAgent applies the five factors in the benchmark explanation: requested skills, project evidence, actual-project relevance, location, and relevant employment/activity. It uses the explanation's 0–3 overall relevance grades and direct-project-over-skills principle; it does not invent numeric factor weights or use benchmark candidate IDs to rank. Shallow interview-prep/cheat-sheet materials, tutorials, forks, empty repositories, tag-only matches, and language-only matches do not count as direct project proof.

Run a fresh P@5 benchmark from PowerShell in D:\saral ai:

    .\.venv\Scripts\python.exe .\run_benchmark_precision.py

The runner reads C:\Users\Admin\Downloads\saral_recruiter_benchmark.txt, freshly runs its Q1–Q20 queries through RecruiterAgent, compares returned GitHub handles with the listed handles, and prints per-query and cumulative results. It saves fresh JSON and text reports in this directory. To use a different benchmark path:

    .\.venv\Scripts\python.exe .\run_benchmark_precision.py --benchmark "C:\path\to\benchmark.txt"

Metric: exact-handle overlap P@5 = returned top-five handles present in that query's listed benchmark handles divided by 5. The current text file has some queries with fewer than five listed handles and does not judge all 60 profiles. Therefore this is the benchmark-list overlap requested, not a complete all-profile relevance evaluation. Missing/unlisted profiles count as misses for this metric.

The runner performs fresh retrieval; it does not read saved agent result files. Run it only when you want to spend the time/provider quota for all benchmark queries.
