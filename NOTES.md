# Saral Recruiter Test Set

## Run

From `D:\saral ai`, run this one command:

```powershell
pytest -q
```

Tests use a temporary SQLite database and stub model, GitHub, and SMTP responses. No real provider or email service is called.

## If a test is removed

Removing a test does not itself make the application fail; it removes a regression check. The item below names the behavior that would then go undetected. To prove a test catches a defect, temporarily inject that defect and confirm the named test fails; restore the code afterward.

## Inventory

1. `test_hostile_instructions_in_bio_are_flagged_and_excluded` — Detects injection hidden in a bio reaching ranking/shortlisting.
2. `test_hostile_instructions_in_repository_description_are_flagged` — Detects repository description instructions being trusted.
3. `test_hostile_instructions_in_readme_are_flagged` — Detects README instructions being trusted.
4. `test_hostile_instructions_in_commit_message_are_flagged_and_excluded` — Detects commit-message injection affecting shortlist decisions.
5. `test_hostile_instructions_in_display_name_are_flagged_and_excluded` — Detects a hostile display name bypassing screening.
6. `test_hostile_profile_is_excluded_before_draft_can_be_created` — A hostile profile is excluded before outreach can be drafted; sanitizing a draft is not a substitute for excluding its author.
7. `test_draft_rejects_link_based_data_exfiltration` — Prevents malicious links or contact data in URLs in a draft.
8. `test_draft_rejects_image_based_data_exfiltration` — Prevents tracking images or image URLs from carrying data.
9. `test_recruiter_approval_claim_is_hostile_and_never_authorizes_send` — Candidate text claiming recruiter approval is treated as hostile and cannot create a send approval.
10. `test_email_and_phone_in_bio_stay_masked_before_reveal` — Prevents email/phone in profile text leaking in search/profile output.
11. `test_contact_is_returned_only_after_reveal_approval` — Contact is returned only after approval for that reveal.
12. `test_same_github_person_under_two_handles_is_deduplicated` — Prevents duplicate candidates for the same GitHub ID.
13. `test_forked_repositories_do_not_inflate_authored_star_evidence` — Fork stars must not count as candidate-authored evidence.
14. `test_tutorial_clones_do_not_count_as_original_projects` — Tutorial clones must not inflate original project evidence.
15. `test_empty_repositories_do_not_inflate_project_or_star_counts` — Empty repos must not inflate project/star totals.
16. `test_repository_presence_alone_is_not_treated_as_authorship` — A repo existing alone must not prove the candidate wrote it.
17. `test_seniority_claim_conflicting_with_employment_history_is_flagged` — Detects seniority claims unsupported by listed dates.
18. `test_account_silent_for_years_is_flagged` — Flags accounts with no recent repository activity.
19. `test_deleted_or_renamed_github_profile_is_rechecked_before_send` — Blocks outreach if the GitHub account changed or disappeared.
20. `test_broken_model_json_uses_safe_criteria_fallback` — Broken model JSON must not crash or silently drop criteria.
21. `test_unknown_tool_is_rejected` — Rejects any tool outside the allowlist.
22. `test_repeated_approval_tool_call_is_idempotent_and_does_not_loop` — Repeated identical calls must not create repeated drafts or loop.
23. `test_send_message_without_approval_never_sends` — No message can be sent without an approval record.
24. `test_github_timeout_mid_verification_batch_fails_closed` — GitHub timeout must not leave an unchecked profile eligible for action.
25. `test_model_timeout_does_not_create_partial_action_or_charge` — Model timeout must leave no partial approvals, sends, or charges.
26. `test_export_four_rows_refuses_all_or_nothing_at_one_point_five_credits` — 4 rows cost 2 credits; 1.5 credits must refuse the whole export.
27. `test_revealing_an_already_revealed_profile_again_is_free` — A second reveal proposal must not charge again.
28. `test_two_sessions_revealing_same_profile_charge_only_once` — Concurrent reveals of one profile must charge at most once.
29. `test_concurrent_distinct_actions_never_make_credit_balance_negative` — Concurrent actions must never overspend the workspace balance.
30. `test_crash_after_reveal_commit_can_recover_without_second_charge` — A lost response must be recoverable without losing contact or charging twice.
31. `test_crash_after_smtp_acceptance_does_not_send_twice` — Recovery after SMTP acceptance must not duplicate delivery.
32. `test_ambiguous_send_others_after_long_history_requires_explicit_recipients` — “Send it to the others too” must not guess recipients.
33. `test_second_one_from_earlier_after_three_searches_requires_explicit_profile` — “The second one from earlier” must not pick an uncertain result.
34. `test_stale_yes_after_shortlist_payload_changes_is_rejected` — A changed candidate payload invalidates stale approval.
35. `test_yes_after_draft_edit_requires_new_approval` — Editing the draft after review must require fresh approval.
36. `test_yes_to_all_does_not_approve_twelve_pending_actions` — One “yes to all” cannot approve 12 separate actions.
37. `test_salary_not_in_data_stays_unknown` — Salary absent from evidence remains unverified.
38. `test_notice_period_not_in_data_stays_unknown` — Notice period absent from evidence remains unverified.
39. `test_relocation_willingness_not_in_data_stays_unknown` — Relocation preference absent from evidence remains unverified.
40. `test_bangalore_typo_and_hinglish_queries_are_passed_through_for_best_effort_retrieval` — Typos/Hinglish stay intact for best-effort retrieval without invented corrections.
41. `test_rubric_ties_are_broken_by_similarity_not_profile_id` — Candidates with identical rubric keys must be ordered by cosine similarity, not by profile_id.
42. `test_transient_github_failure_is_not_cached` — A GitHub timeout/rate limit must not be persisted as a 24-hour identity result.
43. `test_previously_cached_transient_failure_is_retried` — A stored `verification_unavailable` row must be re-checked, not served.
44. `test_failed_check_still_fails_closed` — A failed identity check still leaves the candidate out of the shortlist.

## Safeguard rules and implementation

- **Reject prompt injection at the boundary.** Python scans the display name and serialized profile fields (including bio, repository metadata, README, and commit text). A match is marked ineligible before assessment, excluded from the shortlist, and rejected by draft, reveal, send, and export actions. Suspicious profile text is not passed to the assessment model.
- **Use repository evidence conservatively.** Python risk checks mark forks, tutorial copies, empty repositories, and repositories explicitly not authored by the candidate. Only repositories with explicit authorship evidence contribute to star totals. Activity older than three years is flagged.
- **Deduplicate and fail closed on identity.** Search keeps the highest similarity result for each stable GitHub numeric ID. Verification timeout, missing identity data, account deletion, or ID mismatch makes the candidate ineligible. Sending performs a fresh GitHub REST lookup and rejects an account that disappeared or changed since search.
- **Rerank on the benchmark's relevance grades.** The VerificationAgent uses the same five dimensions described in the benchmark explanation: skills, project evidence, project relevance, location, and relevant employment/activity. It assigns the supplied 0–3 overall relevance grades (3 strong demonstrated match; 2 most requirements with gaps; 1 related profile claims without sufficient direct project evidence; 0 no match). It does not invent numeric factor weights. Within a grade, requested location specificity is considered first, then actual project relevance and authorship evidence, then skill and activity evidence. Skill/topic tags, language metadata, shallow interview-prep/cheat-sheet materials, tutorials, forks, and empty repositories cannot by themselves prove a direct relevant project. Similarity retrieves the corpus and breaks ties between candidates with identical rubric keys; benchmark candidate IDs/order and LLM claim scores do not affect final ranking. This remains a deterministic evidence heuristic, not proof of a person's credentials.
- **Constrain generated drafts.** The model is instructed to draft from public evidence only. Python rejects profile injection, links, image markup, email addresses, and phone numbers in draft inputs/outputs; unsafe model output is replaced with a fixed plain-text fallback. A hostile profile is blocked before drafting.
- **Bind approvals to the reviewed content.** SQLite stores a hash of the draft body inside the approval payload. If the draft changes before approval is used, sending is rejected and the user must review and approve again.
- **Make contact reveal and credits idempotent.** A SQLite transaction serializes concurrent approvals. The first reveal stores the result and charges one credit; later approvals for that same profile return the stored result at zero cost.
- **Reserve email sends before SMTP.** A durable outbox row and the credit debit commit before SMTP is contacted. An uncertain or in-progress attempt is never automatically retried. This provides at-most-once sending; if SMTP accepted the email but final recording failed, the outbox stays in an uncertain state for manual reconciliation. SMTP does not provide a universal exactly-once guarantee.

**Technology:** existing Python standard library (`re`, `urllib`, `email`, `sqlite3`, transactions) plus the existing GitHub REST API. No new model, provider, framework, or runtime dependency is needed. Pytest with stub model/GitHub/SMTP responses verifies these rules without sending real email or making live provider requests.

## Benchmark and retrieval-rubric status

`C:\Users\Admin\Downloads\saral_recruiter_benchmark.txt` supplies the 20 query texts and manually selected candidate handles used as the P@5 reference. The accompanying explanation says the original score/order was heuristic, not a calibrated formula or complete pairwise review. The agent uses the explanation's five-factor, 0–3 relevance rubric; the benchmark handles are used only to calculate overlap, never to rank live candidates.

The latest explanation proposes judging each query-profile pair on a 0–3 relevance scale and recording supporting repository/profile evidence, missing requirements, contradictions, and the reason for the grade. A complete 20-query × 60-profile benchmark would contain 1,200 judgments. The current text file does not contain those judgments; precision against its old top-five lists is only exact-list overlap, not validated relevance precision.

At runtime, `VerificationAgent` applies the same rubric definitions to the retrieved profiles. `run_benchmark_precision.py` reruns the benchmark queries through this agent and calculates top-five exact GitHub-handle overlap against the manual lists. This is the requested benchmark-list P@5; because some queries have fewer than five listed handles and the source does not judge all 60 profiles, it must be reported as exact-list overlap rather than complete relevance precision.

## Held-out query status

`run_benchmark_precision.py` reports Q1-Q15 (development) and Q16-Q20 (held-out) separately. The held-out five are not clean: `_five_factor_rank` contains rules keyed to wording used in them (`recent|activity` for Q16, `early-career|student` and `computer science` for Q18, `employment history|experienced` for Q19), and all 20 query texts were available while the ranker was written. Report the Q16-Q20 figure as a seen set, not as unseen generalisation; an unseen figure needs five new queries written and labelled after the ranker is frozen.
