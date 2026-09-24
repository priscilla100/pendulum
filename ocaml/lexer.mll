{
  (** Lexer for PLTL formulas.

      Each operator has multiple surface spellings (symbolic, word-form,
      LaTeX-style) that all reduce to the same Menhir token. The
      pretty-printer in {!Ast} decides the canonical form on output.

      Word-form keywords are accepted in three case variants — all
      lowercase ("globally"), capitalized ("Globally"), and all upper
      ("GLOBALLY"). Mixed-case variants like "GLObally" are not accepted;
      this is a deliberate trade-off so that the lexer can split
      adjacent single-letter operators like "GFp0" into [G F p0] without
      a greedy fallback rule swallowing the leading uppercase letters. *)

  open Parser

  exception Lexical_error of string

  (* Lowercase identifier keyword table. Lowercase tokens like "and"
     and "until" are looked up here; capitalised and ALL-CAPS variants
     are handled by explicit rules below. *)
  let lowercase_keywords = [
    "true",         TRUE;
    "false",        FALSE;
    "and",          AND;
    "land",         AND;
    "or",           OR;
    "lor",          OR;
    "not",          NOT;
    "lnot",         NOT;
    "neg",          NOT;
    "implies",      IMPLIES;
    "iff",          IFF;
    "until",        UNTIL;
    "since",        SINCE;
    "weakuntil",    WEAKUNTIL;
    "release",      RELEASE;
    "trigger",      TRIGGER;
    "next",         NEXT;
    "yesterday",    YESTERDAY;
    "eventually",   EVENTUALLY;
    "finally",      EVENTUALLY;
    "globally",     GLOBALLY;
    "always",       GLOBALLY;
    "henceforth",   GLOBALLY;
    "once",         ONCE;
    "historically", HISTORICALLY;
  ]

  let lookup_lowercase id =
    try Some (List.assoc id lowercase_keywords)
    with Not_found -> None
}

let lowercase = ['a'-'z']
let uppercase = ['A'-'Z']
let alpha     = ['A'-'Z' 'a'-'z']
let digit     = ['0'-'9']

(* Propositional atoms: lowercase letter start; lowercase letters,
   digits, and underscores in the tail. Underscores are allowed since
   names like [can_access] and [req_valid] are idiomatic in real specs. *)
let lower_id  = lowercase (lowercase | digit | '_')*

(* Identifier-suffix character class. Used by the "keyword-with-bad-suffix"
   trap rules below: a known keyword immediately glued to alphanumerics
   like "Globallyp" must NOT silently parse as a keyword token followed
   by an atom — that would let malformed input slip through. *)
let id_suffix = (alpha | digit | '_')+

let whitespace = [' ' '\t' '\r' '\n']

rule token = parse
  | whitespace+        { token lexbuf }
  | "(*"               { comment 0 lexbuf }

  (* ── punctuation ──────────────────────────────────────────────────── *)
  | '('                { LPAREN }
  | ')'                { RPAREN }

  (* ── biimplication: <-> <=> \iff \leftrightarrow ─────────────────────── *)
  | "<->"              { IFF }
  | "<=>"              { IFF }
  | "\\iff"            { IFF }
  | "\\leftrightarrow" { IFF }

  (* ── implication: -> => \implies \to \rightarrow ─────────────────────── *)
  | "->"               { IMPLIES }
  | "=>"               { IMPLIES }
  | "\\implies"        { IMPLIES }
  | "\\to"             { IMPLIES }
  | "\\rightarrow"     { IMPLIES }

  (* ── disjunction: | || \/ \vee \lor ──────────────────────────────────── *)
  | "||"               { OR }
  | "|"                { OR }
  | "\\/"              { OR }
  | "\\vee"            { OR }
  | "\\lor"            { OR }

  (* ── conjunction: & && /\ \wedge \land ───────────────────────────────── *)
  | "&&"               { AND }
  | "&"                { AND }
  | "/\\"              { AND }
  | "\\wedge"          { AND }
  | "\\land"           { AND }

  (* ── negation: ! ~ \neg \lnot ────────────────────────────────────────── *)
  | "!"                { NOT }
  | "~"                { NOT }
  | "\\neg"            { NOT }
  | "\\lnot"           { NOT }

  (* ── temporal: globally  G [] \G \Box \square ────────────────────────── *)
  | "[]"               { GLOBALLY }
  | "\\G"              { GLOBALLY }
  | "\\Box"            { GLOBALLY }
  | "\\square"         { GLOBALLY }

  (* ── temporal: eventually  F <> \F \Diamond \lozenge ─────────────────── *)
  | "<>"               { EVENTUALLY }
  | "\\F"              { EVENTUALLY }
  | "\\Diamond"        { EVENTUALLY }
  | "\\lozenge"        { EVENTUALLY }

  (* ── temporal: next  X \X \Next \bigcirc \circ ───────────────────────── *)
  | "\\X"              { NEXT }
  | "\\Next"           { NEXT }
  | "\\bigcirc"        { NEXT }
  | "\\circ"           { NEXT }

  (* ── temporal: yesterday  Y \Y \prev ─────────────────────────────────── *)
  | "\\Y"              { YESTERDAY }
  | "\\prev"           { YESTERDAY }

  (* ── temporal: historically  H \H \boxminus ─────────────────────────── *)
  | "\\H"              { HISTORICALLY }
  | "\\boxminus"       { HISTORICALLY }

  (* ── temporal: once  O \O \Once \diamondminus ───────────────────────── *)
  | "\\O"              { ONCE }
  | "\\Once"           { ONCE }
  | "\\diamondminus"   { ONCE }

  (* ── binary temporal LaTeX-style ─────────────────────────────────────── *)
  | "\\U"              { UNTIL }
  | "\\S"              { SINCE }
  | "\\W"              { WEAKUNTIL }
  | "\\R"              { RELEASE }
  | "\\T"              { TRIGGER }

  (* ── Capitalised and ALL-CAPS variants of word-form keywords ─────────── *)
  | "True"  | "TRUE"           { TRUE }
  | "False" | "FALSE"          { FALSE }
  | "And"   | "AND"            { AND }
  | "Land"  | "LAND"           { AND }
  | "Or"    | "OR"             { OR }
  | "Lor"   | "LOR"            { OR }
  | "Not"   | "NOT"            { NOT }
  | "Lnot"  | "LNOT"           { NOT }
  | "Neg"   | "NEG"            { NOT }
  | "Implies"  | "IMPLIES"     { IMPLIES }
  | "Iff"      | "IFF"         { IFF }
  | "Until"      | "UNTIL"     { UNTIL }
  | "Since"      | "SINCE"     { SINCE }
  | "WeakUntil"  | "Weakuntil" | "WEAKUNTIL" { WEAKUNTIL }
  | "Release"    | "RELEASE"   { RELEASE }
  | "Trigger"    | "TRIGGER"   { TRIGGER }
  | "Next"       | "NEXT"      { NEXT }
  | "Yesterday"  | "YESTERDAY" { YESTERDAY }
  | "Eventually" | "EVENTUALLY" { EVENTUALLY }
  | "Finally"    | "FINALLY"   { EVENTUALLY }
  | "Globally"   | "GLOBALLY"  { GLOBALLY }
  | "Always"     | "ALWAYS"    { GLOBALLY }
  | "Henceforth" | "HENCEFORTH" { GLOBALLY }
  | "Once"       | "ONCE"      { ONCE }
  | "Historically" | "HISTORICALLY" { HISTORICALLY }

  (* ── Word-boundary traps ──────────────────────────────────────────────

     A capitalised/ALL-CAPS keyword or backslash command directly glued
     to identifier characters (e.g. "Globallyp", "p ANDq", "\Gfoo",
     "\tofoo") would otherwise be silently split into [keyword] [atom]
     by longest-match. These trap rules force such inputs to be lexical
     errors, matching one character longer than the bare keyword and so
     winning the longest-match contest.

     Single-letter uppercase operators (G, F, X, …) are intentionally
     NOT trapped because adjoining them is meaningful: "GFp0" must lex
     as [G][F][p0], the way real Spot/NuSMV formulas write it. *)
  | ( "True" | "TRUE" | "False" | "FALSE"
    | "And"  | "AND"  | "Land"  | "LAND"
    | "Or"   | "OR"   | "Lor"   | "LOR"
    | "Not"  | "NOT"  | "Lnot"  | "LNOT" | "Neg" | "NEG"
    | "Implies" | "IMPLIES" | "Iff" | "IFF"
    | "Until"   | "UNTIL"   | "Since" | "SINCE"
    | "WeakUntil" | "Weakuntil" | "WEAKUNTIL"
    | "Release" | "RELEASE" | "Trigger" | "TRIGGER"
    | "Next" | "NEXT" | "Yesterday" | "YESTERDAY"
    | "Eventually" | "EVENTUALLY" | "Finally" | "FINALLY"
    | "Globally" | "GLOBALLY" | "Always" | "ALWAYS"
    | "Henceforth" | "HENCEFORTH"
    | "Once" | "ONCE" | "Historically" | "HISTORICALLY"
    ) id_suffix as bad {
      raise (Lexical_error
        (Printf.sprintf
           "invalid identifier glued to keyword: %S (insert whitespace)" bad))
    }

  | ( "\\neg" | "\\lnot"
    | "\\wedge" | "\\land"
    | "\\vee"   | "\\lor"
    | "\\implies" | "\\to" | "\\rightarrow"
    | "\\iff" | "\\leftrightarrow"
    | "\\G" | "\\Box" | "\\square"
    | "\\F" | "\\Diamond" | "\\lozenge"
    | "\\X" | "\\Next" | "\\bigcirc" | "\\circ"
    | "\\Y" | "\\prev"
    | "\\H" | "\\boxminus"
    | "\\O" | "\\Once" | "\\diamondminus"
    | "\\U" | "\\S" | "\\W" | "\\R" | "\\T"
    ) id_suffix as bad {
      raise (Lexical_error
        (Printf.sprintf
           "invalid identifier glued to LaTeX command: %S (insert whitespace)" bad))
    }

  (* ── single-uppercase-letter operators (case-sensitive) ──────────────── *)
  | "G"                { GLOBALLY }
  | "F"                { EVENTUALLY }
  | "X"                { NEXT }
  | "Y"                { YESTERDAY }
  | "H"                { HISTORICALLY }
  | "O"                { ONCE }
  | "U"                { UNTIL }
  | "S"                { SINCE }
  | "W"                { WEAKUNTIL }
  | "R"                { RELEASE }
  | "T"                { TRIGGER }

  (* Lowercase-starting word: either a propositional atom or one of the
     lowercase keyword aliases such as "and" / "until" / "true". *)
  | lower_id as id {
      match lookup_lowercase id with
      | Some tok -> tok
      | None     -> IDENT id
    }

  | eof                { EOF }
  | _ as c             {
      raise (Lexical_error
        (Printf.sprintf "unexpected character %C" c))
    }

(* Nested OCaml-style block comments, ignored. *)
and comment depth = parse
  | "(*"               { comment (depth + 1) lexbuf }
  | "*)"               { if depth = 0 then token lexbuf
                         else comment (depth - 1) lexbuf }
  | eof                { raise (Lexical_error "unterminated comment") }
  | _                  { comment depth lexbuf }
