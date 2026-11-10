# tt

A small command-line time tracker for work orders and the steps within each
order. One Python file, standard library only (Python 3.10+).

Data is stored in SQLite at `~/.local/share/tt/tt.db`, created on first run.
Timers are stored as timestamps, so they keep counting after you close the
terminal or reboot.

## Install

```sh
git clone <this repo> ~/src/TimeTracker
chmod +x ~/src/TimeTracker/tt
mkdir -p ~/.local/bin
ln -s ~/src/TimeTracker/tt ~/.local/bin/tt
```

If `tt` is not found afterwards, add `~/.local/bin` to your `PATH`
(`export PATH="$HOME/.local/bin:$PATH"` in `~/.bashrc` or `~/.zshrc`).

## Usage

```sh
tt start 40000123          # open order 40000123 at the first step, start its timer
tt start 40000999 assemble # a second order; the first timer keeps running
tt switch 123              # pause everything else, work on 40000123
tt step as                 # 40000123: "pick" is complete, now on "assemble"
tt step 3                  # steps also go by number: now on "test"
tt note waiting on parts   # note on the current entry
tt pause                   # break
tt resume
tt done                    # stop the timer, mark 40000123 complete
tt                         # same as tt status
```

### Choosing the order

- Leave the order out and `tt` uses the order you touched most recently. The
  confirmation line always names the order it acted on.
- An order argument can be any unique prefix or suffix of an open order's ID,
  such as the last 3 digits. If several orders match, `tt` lists them.
- `tt start` and `tt switch` use an existing order when the argument matches
  one, and create a new order only when nothing matches. To create an order
  whose ID is part of an open order's ID, use `tt start --new 123`.
- Starting an order that is already done reopens it.

### Commands

| Command | What it does |
|---|---|
| `tt start [order] [step]` | Open the order if new and start its timer. Other timers keep running. |
| `tt switch [order] [step]` | Pause all other running timers, then start or resume this one. |
| `tt step <step> [order]` | Move to a new step. Closes the previous step's entry and marks that step complete. |
| `tt pause [order \| --all]` | Pause a timer. Paused time is not counted as work. |
| `tt resume [order]` | Resume a paused timer (or start a stopped one). |
| `tt stop [order \| --all]` | Stop the timer and leave the order open. |
| `tt done [order]` | Stop the timer, mark the current step and the order complete. |
| `tt status` | Open orders with step, state, and elapsed time. `*` marks the most recent order. |
| `tt show [order]` | Time per step and total for one order (also works for done orders). |
| `tt report [range]` | Orders with steps completed and total time. Defaults to today. |
| `tt export [--csv FILE] [range]` | CSV export. Defaults to all time; without `--csv` it prints to the terminal. |
| `tt note <text> [-o order]` | Attach a note to the order's current entry. No quotes needed. |
| `tt edit` | List the 10 most recent entries (`-n 25` for more). |
| `tt edit 12 --start 9:15 --end 10:40` | Change entry 12's start and/or end. |
| `tt edit 12 --delete` | Delete entry 12. |

`[range]` is one of `--today`, `--week` (Monday through today), or
`--from 2026-03-01 --to 2026-03-15` (either end may be left out). An entry
belongs to the day it started.

Edit times are `HH:MM` (same day as the entry) or `'YYYY-MM-DD HH:MM'`.

Giving `start` or `switch` a step that differs from the order's current step
moves the order to that step, the same as `tt step`.

### Order IDs with special characters

Quote any ID containing characters your shell treats specially
(`# $ & ; * ? ( ) < > |` and spaces), otherwise the shell changes or splits it
before `tt` sees it:

```sh
tt start 'A#12/5'
tt start 'PO$77;B'
```

An ID that begins with a dash needs `--` in front: `tt start -- -55`.

## Editing the CONFIG block

Open the `tt` file in a text editor. Everything you are meant to change is in
the block marked `CONFIG` at the top; each setting has a comment. Changes take
effect the next time you run `tt`.

**1. STEPS** – `STEPS` is the ordered list of step names. New orders begin at
the first one. Step numbers on the command line follow this order. Renaming a
step does not rename it in time already recorded.

**2. ORDER ID VALIDATION**

- `ORDER_ID_REGEX` is the pattern a new order ID must match. The default
  accepts any 1 to 40 non-whitespace characters. Stricter patterns (exactly 8
  digits; digits with dashes; letters, digits and `- _ / # .`) sit underneath
  it, commented out: put a `#` in front of the active line and remove the `#`
  from the one you want.
- `ORDER_ID_NORMALIZE` is `"strip"` (trim whitespace), `"strip_upper"` (trim
  and uppercase), or `"none"`.

**3. CSV EXPORT**

| Setting | Meaning |
|---|---|
| `CSV_COLUMNS` | Fields to export, in order: `order_id`, `step`, `date`, `start`, `end`, `duration`, `paused_time`, `order_status`, `note`. |
| `CSV_HEADERS` | Header text for each field, to match another system's column names. |
| `CSV_ROW_MODE` | `"entry"` (one row per time entry), `"step"` (one row per order and step), or `"order"` (one row per order). |
| `CSV_DURATION_FORMAT` | `"decimal_hours"` (1.25), `"minutes"` (75), or `"h:mm"` (1:15). |
| `CSV_ROUND_MINUTES` | Round durations to the nearest N minutes: 15 = quarter hour, 1 = minute, 0 = off. |
| `CSV_DATE_FORMAT`, `CSV_TIME_FORMAT` | [strftime](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes) formats for the date and the start/end columns. |
| `CSV_DELIMITER` | Field separator, e.g. `","`, `";"` or `"\t"`. |
| `CSV_INCLUDE_HEADER` | `True` to write the header row. |

In `step` and `order` modes, durations are summed and then rounded once per
row; `start` is the earliest start, `end` the latest end, and notes are joined
with `; `. A timer that is still running is exported with time counted up to
now and an empty `end`.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

To try commands without touching your real data, point `tt` at another
database: `TT_DB=/tmp/try.db tt start 123`.
