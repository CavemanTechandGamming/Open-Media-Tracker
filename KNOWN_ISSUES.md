# Known issues — Open Media Tracker

These are **acknowledged limitations** the maintainers intend to improve. They set expectations and help avoid duplicate bug reports. For supported scope (e.g. local storage), see the [README](README.md).

---

| # | Issue | What’s going on |
|---|--------|------------------|
| **1** | **Duplicate TV rows after renaming a folder** | Each show is stored by **`folder_path`** (unique). If you **rename** a folder on disk, the next scan treats it as a **new** path and inserts another **`Media`** row. The **old** row is not removed automatically, so the same series can appear **twice** (old name + new name) until you clean the database or we add prune/dedupe logic. |
| **2** | **“Missing” counts vs which episodes** | The TV table shows **X/Y collected** and a **missing count** derived from totals. The **episode audit** panel (after opening a row) lists missing episodes from **`Episode`** rows where **`exists_locally`** is false. If those **counts and rows drift** (e.g. partial sync), or you open a **different duplicate row** for the same show (see issue 1), the summary and the detailed list can **feel inconsistent**. We plan to align “missing” to a single source of truth and make the missing list easier to reach. |
| **3** | **Horizontal scroll and fixed-width layout** | Tables and wide rows can force **left–right scrolling** on smaller screens; the main layout does **not** span the full width on large displays and does **not** resize smoothly when the **window size changes**. Responsive layout and table wrapping are planned. |
