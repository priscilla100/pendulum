# SALT — Compiler in Docker, for an NL→LTL Agent

This folder packages the [SALT compiler v1.0.1](https://www.isp.uni-luebeck.de/salt)
(Structured Assertion Language for Temporal Logic, TU München) so that another
agentic Claude can invoke it as a black‑box tool to turn **SALT specifications**
into **propositional LTL** in SMV syntax.

The intended pipeline is:

```
free-form natural language
        │  (other Claude — out of scope here)
        ▼
SALT specification           ← what the agent must produce
        │  (this tool)
        ▼
LTL formula (SMV syntax)     ← what gets returned
```

Everything in this README is **untimed-only**. The `-notimed` flag is treated as
mandatory and is baked into every example below. The timed layer (`timed[~c]`,
TLTL output) is intentionally not exposed.

> If you are the consuming agent: read §1 to invoke the container, §3 to learn
> the SALT surface you can emit, and §4 for ready-to-copy translation patterns.

---

## 1. Running SALT

### 1.1 Container

The image is built from the local `Dockerfile`:

```bash
docker build -t salt-compiler:latest .
```

It contains:
- `eclipse-temurin:17-jdk` (Java runtime SALT needs)
- `ghc` 9.x as the Haskell backend (`hs.properties` is preconfigured)
- The SALT 1.0.1 binary distribution at `/opt/salt`
- A patched copy of the Haskell sources (`import List` → `import Data.List`,
  etc.) so it runs against modern GHC
- A wrapper at `/usr/local/bin/salt` as the entrypoint

The entrypoint is the compiler itself, so the container takes SALT CLI flags
directly:

```bash
docker run --rm salt-compiler:latest -h
```

### 1.2 Three invocation modes

| Mode             | Command                                                                                                  | Use when                                            |
| ---------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `-f "<spec>"`    | `docker run --rm salt-compiler:latest -notimed -f "assert always p"`                                     | Spec is a short string the agent built in memory.   |
| stdin pipe       | `echo "assert always p" \| docker run --rm -i salt-compiler:latest -notimed`                             | Spec is multi-line / generated programmatically.    |
| file in/file out | `docker run --rm -v $PWD:/work salt-compiler:latest -notimed /work/spec.salt -o /work/out.ltl`           | Persisting either side of the translation to disk.  |

`-i` is required for the stdin form. For file modes, mount the agent's working
directory to `/work` (the container's WORKDIR).

### 1.3 Exit codes and error reporting

| Exit | Stdout                  | Stderr                                       | Meaning                                  |
| ---- | ----------------------- | -------------------------------------------- | ---------------------------------------- |
| 0    | `LTLSPEC <formula>`     | empty (or verbose status lines if `-v`)      | success                                  |
| 1    | empty                   | `ERROR: …` lines (preceded by verbose status if `-v`) | parse error, undeclared variable, semantic error, forbidden operator (e.g. timed/past/next when its `-no*` flag is set) |

The agent **must always capture stderr separately** and treat exit ≠ 0 as
"specification rejected — show stderr verbatim to the upstream Claude so it can
revise the SALT spec." Without `-v`, a non-empty stderr never accompanies a
successful formula on stdout, so a single "exit code or stderr non-empty"
check is reliable for the recommended invocation.

---

## 2. Mandatory and recommended flags

| Flag         | Default in this tool | Purpose                                                                                          |
| ------------ | -------------------- | ------------------------------------------------------------------------------------------------ |
| `-notimed`   | **always pass it**   | Reject any timed operator (`timed[~c]`, `next timed[…]`, etc.). Keeps output pure propositional LTL. |
| `-smv`       | default              | SMV-style output: `!`, `&`, `\|`, `->`, `<->`, `G F U V X H O S T Y Z`. This is what your downstream consumer reads. |
| `-ltl`       | default              | Emit LTL (not the intermediate SALT-- or Haskell forms). |
| `-nopast`    | optional             | Forbids past operators (`once`, `since`, `historically`, `previous`, …). The downstream consumer **can** handle past — leave this off unless you want to artificially restrict the language. |
| `-nonext`    | optional             | Forbids `next` and anything that desugars through it (notably regular expressions). Use only if downstream is stutter-invariant. |
| `-spin`      | skip                 | Switches output to SPIN syntax (`[]`, `<>`, `&&`, `||`, `U V X`). Wrong target for this project. |
| `-latex`     | skip                 | LaTeX prettyprint.                                                                               |
| `-e`         | situational          | Embedded mode: copies a host file through, replacing `BEGINSALT … ENDSALT` blocks with compiled LTL. Only useful when the SALT spec is embedded inside an SMV model file. |
| `-o <file>`  | optional             | Write to file instead of stdout.                                                                 |
| `-v`         | optional             | Verbose status messages on stderr.                                                               |

### 2.1 Recommended default invocation for this project

```
salt -notimed -smv -ltl
```

This setup:
- guarantees the timed layer is off (no TLTL leakage),
- emits SMV-syntax LTL with the operator set `G F U V X` (future) and
  `Y H O S T` (past), plus boolean `! & | -> <->`.

The downstream agent handles all of these. See §2.2 for why no additional
restriction is needed.

### 2.2 SMV operator coverage — V/Z vs R/T/W

The downstream agent handles `R` (Release), `T` (Trigger), `W` (Weak Until),
and strict `Y` (previous). Mapping that against SMV's letter set:

| SMV letter SALT may emit | Standard LTL name      | Downstream supports? |
| ------------------------ | ---------------------- | -------------------- |
| `G F X U`                | always / eventually / next / until | ✓                    |
| `V`                      | **Release (= R)**      | ✓ — V and R are the same operator, just SMV's symbol vs LTL's symbol. |
| `Y`                      | previous (strict)      | ✓                    |
| `H`                      | historically           | ✓                    |
| `O`                      | once                   | ✓                    |
| `S`                      | since                  | ✓                    |
| `T`                      | trigger (= past R)     | ✓                    |
| `Z`                      | previous **weak**      | n/a — **never emitted**, see below |

Two things to know:

1. **`V` is `R`.** SALT prints `assert a releases b` as `LTLSPEC a V b`.
   That `V` is exactly the Release operator your agent knows as `R`. No
   rewriting is needed; the consuming code can treat `V` as a synonym for `R`.

2. **`Z` never appears in SMV output from SALT 1.0.1.** The only construct
   that would naturally print as `Zφ` is `previous weak φ` (alias
   `nextinpast weak φ`). The SMV printer pre-translates it to
   `!(Y(!φ))` — verified by exhaustive probing of every past construct in the
   language (`previous weak`, `nextinpast weak`, `since weak`,
   `previousn[<=n]`, `occurringinpast`, `holdinginpast`, past regex, …).
   So `Z` is a non-issue in practice.

3. **`W` (Weak Until) is also never literally emitted.** SMV has no
   single-letter Weak-Until operator; SALT desugars `until weak` and
   `since weak` to negated `U`/`S` forms. Your agent's `W` support is not
   exercised from this output — but nothing breaks either.

**Implication:** the agent can emit the full untimed SALT language —
`releases`, `triggered`, `once`, `since`, `historically`, past regex, past
counting, etc. — without further restriction. A defensive post-translation
grep for `\bZ\b` in the output is still cheap and worth keeping, in case a
future SALT version changes its printer.

---

## 3. SALT syntax reference (untimed only)

This section is condensed from the manual (chapters 4–5). It covers everything
the agent needs to emit; the timed layer (§5.4 of the manual) is deliberately
omitted.

### 3.1 Top-level shape

```
[ declare p1, p2, …       ]    -- optional; if present, every atomic
                               --   proposition must be declared
[ define name(x, y) := … ]*    -- zero or more macros (must come BEFORE
                               --   the first assert)
 assert  <expression>           -- one or more assertions; each is compiled
[assert  <expression>]*         --   to a separate LTLSPEC line
```

- Comments start with `--` and run to end of line.
- Identifiers: `[A-Za-z_][A-Za-z0-9_]*`. Case-sensitive.
- Anything that is not a keyword/macro/parameter is treated as a boolean
  variable. Misspelling `eventually` as `eventuall` will silently make it a
  variable name unless you wrap the spec with `declare`.
- Boolean literals: `true`, `false`.
- **Quoted atomic propositions** can be any string, passed through verbatim:
  `assert always "queuelength == 0"` is legal and useful when downstream is an
  SMV model with non-boolean predicates. The manual documents an escape rule
  (`\"`, `\$`) for embedding `"` or `$` inside a quoted proposition, but the
  shipped 1.0.1 compiler mishandles those escapes (passes raw to GHC and
  crashes). Avoid embedded quotes if possible; if unavoidable, generate the
  spec via a file and inspect stderr.

#### Reserved keywords — do not use as variable names

Every SALT operator/modifier is reserved. Trying to use one as an atomic
proposition produces `ERROR: unexpected token: <kw>`. The full reserved set
(verified by probing the 1.0.1 compiler):

```
assert  define  declare
true  false
always  never  eventually  next  until  releases
historically  once  since  triggered  previous
alwaysinpast  eventuallyinpast  neverinpast  untilinpast  releasesinpast
nextinpast  frominpast  uptoinpast  betweeninpast
occurringinpast  holdinginpast  nextninpast  previousn
upto  before  from  after  between  rejecton  accepton
occurring  holding  nextn
req  opt  weak  incl  excl  required  optional  inclusive  exclusive
and  or  not  implies  equals
if  then  else
allof  noneof  someof  exactlyoneof  in  as  list  enumerate  with  without
timed
```

Practical guidance for the agent: when a natural-language requirement mentions
something like "request" or "open", those are safe (`request`, `open`,
`answer`, `floor`, `door` are all free identifiers). But `until` and `before`
are reserved, so an NL phrase like "stays open until the timer expires" must
not produce an identifier named `until`. When in doubt, mangle: `door_open`,
`req_signal`, `tmr_expired`.

#### Operator precedence (manual §5.1, highest first)

1. `( )` parentheses
2. `!`  — symbolic unary boolean
3. `& | -> <->` — symbolic binary boolean (**all four have equal
   precedence**; mixing them without parens produces a compiler warning and
   right-associative parse)
4. `* + ?` — repetition (regex)
5. `; :` — sequence (regex)
6. prefix macro calls, unary built-ins (`always`, `next`, …), modifiers
   (`optional`, …)
7. infix macro calls, binary built-ins (`until`, `and`, …)
8. `if`-`then`, `if`-`then`-`else`, iteration operators

When in doubt, parenthesise. Word forms (`and`, `or`, …) get a *lower*
precedence than their symbolic counterparts because they are parsed as macro
calls.

### 3.2 Boolean (propositional) layer

| Operator | Symbol  | Word form  |
| -------- | ------- | ---------- |
| not      | `!`     | `not`      |
| and      | `&`     | `and`      |
| or       | `\|`    | `or`       |
| implies  | `->`    | `implies`  |
| iff      | `<->`   | `equals`   |

Also: `if φ then ψ`. SALT 1.0.1 parses `if-then` cleanly, but its `else`
branch only accepts another `if` (a chained `else if … then …`), not a plain
expression — the manual claims `else ρ` is supported, but the shipped compiler
rejects it with `expecting "if"`. **The safe pattern is**:

| Want                            | Write                                          |
| ------------------------------- | ---------------------------------------------- |
| `ψ` when `φ`, no else           | `if φ then ψ`                                  |
| `ψ` when `φ`, `ρ` otherwise     | `(φ -> ψ) & (!φ -> ρ)`  *(or use word forms)* |
| Cascaded if/elseif              | `if φ then ψ else if χ then ρ`  *(works)*     |

### 3.3 Future temporal operators

| SALT                   | LTL    | Meaning                                                                 |
| ---------------------- | ------ | ----------------------------------------------------------------------- |
| `always φ`             | □ φ    | φ holds now and at every future step.                                   |
| `never φ`              | ¬◇ φ   | φ never holds from now on.                                              |
| `eventually φ`         | ◇ φ    | φ holds now or at some future step.                                     |
| `next φ`               | ○ φ    | φ holds in the next step (strong).                                      |
| `next weak φ`          | ○_W φ  | Like `next` but vacuously true at the end of a trace.                   |
| `φ until ψ`            | φ U ψ  | ψ eventually holds; until then φ holds.                                 |
| `φ until weak ψ`       | φ W ψ  | Either φ forever, or `φ until ψ`. Compiles to a negated-`U` form (no `V`/`W` symbol in the output). |
| `φ releases ψ`         | φ R ψ  | Per manual §6.1.2, equivalent to `ψ until incl weak φ`. Compiles to `V` in SMV output — `V` is just SMV's letter for Release, see §2.2. |

**Extended `until` variants** (manual §5.3.1). The plain forms above are
shorthand: `φ until ψ` = `φ until excl req ψ`, `φ until weak ψ` =
`φ until excl weak ψ`. The remaining combinations are useful when ψ's
behaviour at the boundary matters:

| Form                          | Equivalent to                                          |
| ----------------------------- | ------------------------------------------------------ |
| `φ until excl opt ψ`          | "if ψ ever holds, φ holds up to (excl.) that point"    |
| `φ until incl req ψ`          | `φ U (φ ∧ ψ)` — ψ must occur, and φ must hold at ψ's step too |
| `φ until incl opt ψ`          | `(◇ψ) → (φ U (φ ∧ ψ))`                                  |
| `φ until incl weak ψ`         | `ψ R φ` (= `releases` with swapped args)               |

### 3.4 Scope operators — `upto`, `from`, `between`

These let you say "φ holds *before* / *after* / *between* events" without
nested `□ ◇` boilerplate.

```
[{required|weak}] φ upto    {inclusive|exclusive} {required|optional|weak} b
                  φ from    {inclusive|exclusive} {required|optional}      a
                  φ between {inclusive|exclusive} {required|optional}      a,
                            {inclusive|exclusive} {required|optional|weak} b
```

Aliases: `before` = `upto`, `after` = `from`. The short modifier names
`req`/`opt`/`incl`/`excl` are accepted everywhere.

The two right-hand modifier slots **must always be filled**; omitting them
produces:
```
ERROR:
Operator must be used with inclusive/exclusive and required, optional or weak at line 1:NN
```

**Boundary modifiers (right side):**

- **inclusive / exclusive** — is the boundary step (`a` or `b`) itself part of
  the interval where φ is checked?
- **required / optional / weak** — what happens if the boundary event never
  occurs?
  - `required b` — false (the boundary *must* occur).
  - `optional b` — true (no boundary, no obligation).
  - `weak b`     — the obligation continues over the whole remaining trace
    just like `until weak` would. So `always a upto excl weak b` is true on
    `aaaa…` (no `b`, but `a` holds forever) and false on `----…` (no `b`, and
    `a` fails immediately). `weak` is only allowed on the `upto` side or on
    `between`'s end condition.

**Optional left modifier on `upto`:**

When the φ side is just a bare proposition under an *exclusive* `upto` /
`between`, you must pick what happens if the boundary fires at the current
step (i.e. the scope is empty):

- `required p upto excl req b` — `LTLSPEC (F b) & ((!b) & p)` (empty scope is
  treated as false).
- `weak p upto excl req b` — `LTLSPEC (F b) & (b | p)` (empty scope is true).

A bare `p upto excl req b` errors:
`ERROR: Explicit required or weak needed at line 1:NN`. The compiler is
asking you to disambiguate.

Manual §5.3.2 spells out which φ are accepted directly:

- ✅ no prefix needed: `always φ`, `never φ`, `eventually φ`, `φ until ψ`,
  `φ until weak ψ`, `releases`, and boolean combinations (`!`, `&`, `|`,
  `->`, `<->`) of any of these — booleans recurse into their sub-expressions.
- ⚠️ prefix required: bare propositions and anything that would otherwise be
  ambiguous on an empty interval. Use `required φ` (false on empty) or
  `weak φ` (true on empty).
- ❌ everything else is illegal as the immediate argument of an exclusive
  `upto`/`between`.

This restriction does *not* apply to inclusive `upto`/`between`, because an
inclusive boundary guarantees the interval is at least one step long.

**No implicit `always`:**

Scope operators do *not* wrap their φ in `always`. `p upto excl req b` checks
`p` only at the current step. To require `p` at every step until `b`, write
`always p upto excl req b`. This is the source of most subtle bugs in
agent-emitted SALT.

**Past operators are unbounded inside future scopes:**

`from`/`upto`/`between` do not constrain past operators in their argument.
`(always (x -> once y)) from incl req a` allows `y` to have occurred
arbitrarily far back in time — before `a`. To limit `once y` to the time after
`a`, write `once y uptoinpast incl req a` inside.

**Worked example** (returns-before-terminates):
```
assert (eventually result) before exclusive required term
```
yields `LTLSPEC (F term) & ((!term) U (result & (!term)))`.

### 3.5 Counting quantifiers

```
occurring[=n] φ   occurring[n] φ      occurring[n..m] φ
occurring[>n] φ   occurring[>=n] φ    occurring[<n] φ   occurring[<=n] φ

holding[=n]   φ   holding[n]   φ      holding[n..m]   φ
holding[>n]   φ   holding[>=n]   φ    holding[<n]   φ   holding[<=n]   φ
```

`[=n]` and the bare `[n]` form are synonyms. `occurring` counts each
*consecutive run* of φ as one occurrence; `holding` counts each *step*.

**Important:** the bounded forms (`[=n]`, `[n..m]`, `[<n]`, `[<=n]`) impose a
"no more after" rule — after the last counted occurrence/run, φ must *never*
hold again (manual §5.3.5). The unbounded `>=n` and `>n` forms allow further
occurrences. So `occurring[<=2] p` asserts "at most two runs of `p`, *ever*",
not "at most two so far".

Elevator-style example from the manual:
```
assert always (occurring[<=2] atfloor
               between incl optional call, excl optional open)
```

### 3.6 `nextn[…]` — finite next chains

```
nextn[=n] φ       nextn[n] φ      -- exactly n steps from now
nextn[n..m] φ                     -- at some step in [n, m]
nextn[>=n] φ      nextn[>n] φ     -- eventually, at least n (or strictly more) steps from now
nextn[<=n] φ      nextn[<n] φ     -- within n (or strictly fewer) steps
```

Only the exact form `nextn[=n] φ` desugars to a pure `X X … X φ` chain. The
range and inequality forms use `F` / disjunction internally (manual §6.1.3),
e.g. `nextn[>2] p` compiles to `X (X (X (F p)))`. All forms are forbidden
under `-nonext`.

### 3.7 Exception operators

```
φ rejecton b      -- evaluation of φ stops; result becomes false if b fires
                  --   before φ was satisfied
φ accepton b      -- evaluation of φ stops; result becomes true if b fires
                  --   before φ was violated
```

`rejecton`/`accepton` have no past counterparts and influence both future and
past sub-expressions of φ.

### 3.8 Regular expressions

```
/ e1 ; e2 : e3 ; e4 /        -- sequence
/ e * /                       -- Kleene star (0+ steps, purely boolean only)
/ e + /                       -- 1+ steps   (purely boolean only)
/ e ? /                       -- 0 or 1 step
/ e *[=n] /  / e *[n] /       -- exactly n consecutive steps
/ e *[n..m] /                 -- between n and m steps
/ e *[>n] /  / e *[>=n] /     -- more than n / at least n steps
/ e *[<n] /  / e *[<=n] /     -- fewer than n / at most n steps
/ e1 / | / e2 /               -- alternation
```

Sequence operators:
- `;` = "then in the next step"
- `:` = "then overlapping by one step" (`p:q` ≡ `p & q` for propositions)

**SREs do not exclude unnamed conditions** (manual §4.4). `/a;b/` says "in
the current step `a` holds, and in the next step `b` holds" — it does *not*
say anything about other propositions. A trace where `a` and `b` both happen
to be true in both steps still matches `/a;b/`. If the requirement is "*only*
`a` then *only* `b`", the agent must add explicit negations:
`/(a & !b); (b & !a)/`.

Constraints (the compiler enforces these):
- The argument of `*`, `*[>n]`, `*[>=n]`, `+` must be **purely boolean**.
- Within a single regex, all elements except the last must be purely boolean
  or other regexes joined by `|`.
- The last element of a regex can be any SALT expression.

**Empty elements default to `true`** (manual §5.3.4): an SRE position with no
expression is interpreted as `true`. Therefore `/*;a/` is `/true*;a/` —
"eventually a", and it does *not* require anything specific to hold leading up
to `a`. Similarly, a trailing unbounded `*` is `true*`, which matches the
empty sequence — so `/a;*/` is just `/a/`. The agent should avoid emitting
either form by accident; if the intent is "*for several steps `p` holds, then
`q`*", write `/p+; q/` not `/p*; q/`.

Regular expressions translate to nested `next` chains, so they are forbidden
under `-nonext`.

### 3.9 Macros and iteration

```
define mymacro(x, y) := x implies eventually y
assert request mymacro answer                -- infix form, two args
assert mymacro(request, answer)              -- explicit form

define any_p := p1 | p2 | p3                 -- nullary macro
assert always any_p
```

Macro names can also be passed by reference using `@name`, which lets one
macro accept another as a parameter.

Iteration:

```
allof  <list> as i in φ      -- conjunction over substitutions
someof <list> as i in φ      -- disjunction
noneof <list> as i in φ      -- conjunction of negations
exactlyoneof <list> as i in φ

<list> ::= list[a, b, c]  |  enumerate[n..m]
           ( with φ | without φ )*
```

Inside `φ`, `$i$` interpolates the value into atomic-proposition names:

```
assert allof enumerate[1..4] as i in eventually p_$i$_finished
```
produces (note SALT right-nests the conjunction):
```
LTLSPEC (F p_1_finished) & ((F p_2_finished) & ((F p_3_finished) & (F p_4_finished)))
```

`enumerate[n..m]` is inclusive on both ends. `list[a, b, c]` builds a list
whose entries can be any SALT expressions (not just identifiers). Both
support `with φ` / `without φ` suffixes to add or drop elements.

### 3.10 Past operators

Past operators are fully supported — the downstream consumer handles
`Y H O S T`, and SALT 1.0.1 never emits `Z` in SMV mode (see §2.2). The
operators are:
`once` (= `eventuallyinpast`), `since` (= `untilinpast`), `since weak`
(= `untilinpast weak`), `historically` (= `alwaysinpast`), `neverinpast`,
`triggered` (= `releasesinpast`), `previous` (= `nextinpast`),
`previous weak` (= `nextinpast weak`), `previousn[…]` (= `nextninpast[…]`),
`occurringinpast`, `holdinginpast`, `betweeninpast`, `frominpast`,
`uptoinpast`, and past regex written between backslashes (`\a;b;c\`).

Past operators read right-to-left in time: `a since b` mirrors `a until b`
toward the past. See §5.3.6 of the upstream manual for the full reading-order
discussion.

---

## 4. Translation patterns — natural-language → SALT → LTL

Curated set of patterns the agent should recognise. Every "LTL" cell below is
the **literal stdout** the container produces when called with `-notimed`
(verified by re-running each case during this README's audit).

| Pattern (NL)                                                | SALT                                                                        | LTL (SMV)                                                                |
| ----------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| *X always holds*                                            | `assert always x`                                                           | `LTLSPEC G x`                                                            |
| *X never holds*                                             | `assert never x`                                                            | `LTLSPEC !(F x)`                                                         |
| *X eventually holds*                                        | `assert eventually x`                                                       | `LTLSPEC F x`                                                            |
| *Every request is eventually answered*                      | `assert always (request implies eventually answer)`                         | `LTLSPEC G (request -> (F answer))`                                      |
| *X stays true until Y (Y must occur)*                       | `assert x until y`                                                          | `LTLSPEC x U y`                                                          |
| *X stays true until Y, but Y may never occur*               | `assert x until weak y`                                                     | `LTLSPEC !((!y) U ((!x) & (!y)))`                                        |
| *Returns a result before terminating*                       | `assert (eventually result) before exclusive required term`                 | `LTLSPEC (F term) & ((!term) U (result & (!term)))`                      |
| *Once Y, X must always hold afterwards (Y may or may not happen)* | `assert (always x) from inclusive optional y`                         | `LTLSPEC G (y -> (G x))`                                                 |
| *No work between completion and next request* (DAC99)       | `assert always (never call_doWork between inclusive optional return_Execute, exclusive optional call_Execute)` | `LTLSPEC G ((!return_Execute) \| (return_Execute & ((F call_Execute) -> (!((!call_Execute) U (call_doWork & (!call_Execute)))))))` |
| *Up to two arrivals while a call is open* (DAC99)           | `assert always (occurring[<=2] atfloor between incl optional call, excl optional open)` | (≈30 nested `U`s; produced verbatim — paste into nuSMV)        |
| *Exactly one of n channels active*                          | `assert always (exactlyoneof enumerate[0..3] as i in in_$i$)`               | `LTLSPEC G ((in_0 & (!(in_1 \| (in_2 \| in_3)))) \| …)` (one-hot disjunction) |
| *All n processes eventually finish*                         | `assert allof enumerate[1..4] as i in eventually p_$i$_finished`            | `LTLSPEC (F p_1_finished) & ((F p_2_finished) & ((F p_3_finished) & (F p_4_finished)))` |
| *Quoted predicate (downstream is SMV)*                      | `assert working until weak ("queuelength == 0" \| abort)`                   | `LTLSPEC !((!(queuelength == 0 \| abort)) U ((!working) & (!(queuelength == 0 \| abort))))` |
| *Precedence: answer is preceded by request* (uses past)     | `define precedes(x, y) := if y then once x`<br>`assert always (request precedes answer)` | `LTLSPEC G (answer -> (O request))`                                      |

### 4.1 Anti-patterns

- ❌ Any `timed[~c]` operator — blocked by `-notimed`.
- ❌ Forgetting the `inclusive/exclusive` + `required/optional/weak` modifiers
  on `upto`/`from`/`between` — produces a compile error.
- ❌ A regex `*` / `+` / `*[>n]` on a non-boolean argument (e.g.
  `/(always p)*; q/`) — produces a compile error.
- ❌ Combining SREs with `->` or other boolean operators — only `|`
  alternation between regexes is allowed.
- ⚠️  `releases` is fine semantically (emits `V` ≡ `R`), but if a requirement
  reads more naturally as "X until weak Y", prefer that — it's easier for
  a downstream reader to follow.

---

## 5. Suggested tool surface for the agent

A thin wrapper the orchestrating Claude could expose to its planner:

```python
# Pseudocode — the agent's MCP/tool layer
import re, subprocess

def salt_to_ltl(spec: str,
                forbid_past: bool = False,
                forbid_next: bool = False) -> dict:
    """
    Compile a SALT specification to propositional LTL in SMV syntax.

    Returns:
        { "ok": True,  "ltl": "LTLSPEC ..." }                on success
        { "ok": False, "error": "<stderr verbatim>" }        on rejection
    """
    args = ["-notimed", "-smv", "-ltl"]
    if forbid_past: args.append("-nopast")   # default off — past is supported
    if forbid_next: args.append("-nonext")
    args += ["-f", spec]

    r = subprocess.run(
        ["docker", "run", "--rm", "-i", "salt-compiler:latest", *args],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0 and r.stdout.startswith("LTLSPEC"):
        ltl = r.stdout.strip()
        # Belt-and-braces: SALT 1.0.1 never emits Z in SMV mode, but verify.
        if re.search(r"\bZ\b", ltl):
            return {"ok": False,
                    "error": f"unexpected Z in output: {ltl}"}
        return {"ok": True, "ltl": ltl}
    return {"ok": False, "error": r.stderr.strip() or r.stdout.strip()}
```

When you read the returned LTL: treat `V` as `R` (they are the same Release
operator). The other SMV letters (`G F X U Y H O S T`) translate one-to-one
to their standard LTL names.

Notes for the implementer:
- The `-f "<spec>"` form is fine up to a few hundred characters. For longer
  specs prefer piping on stdin (`docker run -i …` with `input=spec`).
- The container is stateless — every call is a fresh JVM + GHC, costing
  ~0.8 s on this machine regardless of spec size. To amortise that cost,
  batch several `assert …` lines into one invocation: 10 asserts in one call
  take the same ~0.8 s, and each produces its own `LTLSPEC` line on stdout in
  order.
- For end-to-end tests the agent can hand the `LTLSPEC …` output to nuSMV /
  Spot / Owl as input; SALT's output is designed to be consumable verbatim by
  those tools.
- The container only exposes the compiler. The output is plain text — no
  binary preamble — so it can be parsed line-by-line and the agent does not
  need to know anything about the JVM, GHC, or the Haskell intermediate
  passes.

---

## 6. Files in this folder

| Path                  | What it is                                                                          |
| --------------------- | ----------------------------------------------------------------------------------- |
| `Dockerfile`          | Builds `salt-compiler:latest`. Patches CRLF + old `import List`/`Maybe`/`IO`. |
| `salt_extract/`       | Unpacked `salt_bin.zip` from isp.uni-luebeck.de (binary + Haskell helpers + manual). |
| `salt_bin.zip`        | Original archive, kept for reproducibility.                                          |
| `manual.pdf`          | The upstream SALT 1.0.1 Language Reference & Compiler Manual.                       |
| `README.md`           | This file.                                                                          |

To rebuild from scratch:

```bash
curl -sL -o salt_bin.zip "https://www.isp.uni-luebeck.de/software/Salt/Downloads/salt_bin.zip"
unzip -q salt_bin.zip -d salt_extract
docker build -t salt-compiler:latest .
docker run --rm salt-compiler:latest -notimed -f "assert always (p implies eventually q)"
# → LTLSPEC G (p -> (F q))
```
