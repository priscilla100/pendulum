(** Abstract syntax for Propositional Linear Temporal Logic (with past).

    The AST is shared between the OCaml front-end (which constructs it from
    surface syntax) and the Rust back-end (which deserialises the JSON form
    produced here). Everything in this module is canonical: the discriminant
    strings emitted by {!formula_to_json} are part of the cross-language
    contract and must stay in sync with [rust/src/ast.rs]. *)

(** Unary temporal operator codes.

    Future-time operators: [Next] (X), [Eventually] (F), [Globally] (G).
    Past-time operators:   [Yesterday] (Y), [Once] (O), [Historically] (H). *)
type unary_op =
  | Next
  | Yesterday
  | Eventually
  | Globally
  | Once
  | Historically

(** Binary temporal operator codes.

    Future-time: [Until] (U), [WeakUntil] (W), [Release] (R).
    Past-time:   [Since] (S), [Trigger] (T). *)
type binary_op =
  | Until
  | Since
  | WeakUntil
  | Release
  | Trigger

(** PLTL formula AST. Logical and temporal connectives are kept as separate
    constructors (rather than a single [FOp] tagged by a string) so consumers
    can pattern-match without going through string opcodes. *)
type formula =
  | FTrue
  | FFalse
  | FAtom    of string
  | FNot     of formula
  | FAnd     of formula * formula
  | FOr      of formula * formula
  | FImplies of formula * formula
  | FIff     of formula * formula
  | FUnary   of unary_op * formula
  | FBinary  of binary_op * formula * formula

(* ── Canonical operator spellings ──────────────────────────────────────────
   These single-character codes are the on-wire JSON values for the "op"
   field and the symbols emitted by the pretty-printer. Keep them in lock-
   step with [rust/src/ast.rs]. *)

let string_of_unary_op = function
  | Next         -> "X"
  | Yesterday    -> "Y"
  | Eventually   -> "F"
  | Globally     -> "G"
  | Once         -> "O"
  | Historically -> "H"

let string_of_binary_op = function
  | Until     -> "U"
  | Since     -> "S"
  | WeakUntil -> "W"
  | Release   -> "R"
  | Trigger   -> "T"

(** Pretty-printer.

    Binary connectives always emit their own surrounding parentheses, so the
    output is unambiguously re-parseable without needing an explicit [FParen]
    constructor in the AST. Unary connectives and atoms never wrap themselves
    — when their operand is binary, the operand's own parens already serve. *)
let rec string_of_formula = function
  | FTrue           -> "true"
  | FFalse          -> "false"
  | FAtom p         -> p
  | FNot g          -> "!" ^ string_of_formula g
  | FUnary (op, g)  -> string_of_unary_op op ^ " " ^ string_of_formula g
  | FAnd     (a, b) -> "(" ^ string_of_formula a ^ " & "   ^ string_of_formula b ^ ")"
  | FOr      (a, b) -> "(" ^ string_of_formula a ^ " | "   ^ string_of_formula b ^ ")"
  | FImplies (a, b) -> "(" ^ string_of_formula a ^ " -> "  ^ string_of_formula b ^ ")"
  | FIff     (a, b) -> "(" ^ string_of_formula a ^ " <-> " ^ string_of_formula b ^ ")"
  | FBinary (op, a, b) ->
      "(" ^ string_of_formula a ^ " " ^ string_of_binary_op op ^ " "
          ^ string_of_formula b ^ ")"

(** JSON serialiser.

    Every node is an object [{ "type": "<variant>", ... }]. Field names
    ([left], [right], [operand], [name], [op]) are part of the cross-language
    contract; do not rename them without updating the Rust side in lockstep. *)
let rec formula_to_json (f : formula) : Yojson.Safe.t =
  match f with
  | FTrue   -> `Assoc [("type", `String "FTrue")]
  | FFalse  -> `Assoc [("type", `String "FFalse")]
  | FAtom p -> `Assoc [("type", `String "FAtom"); ("name", `String p)]
  | FNot g  -> `Assoc [("type", `String "FNot"); ("operand", formula_to_json g)]
  | FAnd (a, b) ->
      `Assoc [("type", `String "FAnd");
              ("left",  formula_to_json a);
              ("right", formula_to_json b)]
  | FOr (a, b) ->
      `Assoc [("type", `String "FOr");
              ("left",  formula_to_json a);
              ("right", formula_to_json b)]
  | FImplies (a, b) ->
      `Assoc [("type", `String "FImplies");
              ("left",  formula_to_json a);
              ("right", formula_to_json b)]
  | FIff (a, b) ->
      `Assoc [("type", `String "FIff");
              ("left",  formula_to_json a);
              ("right", formula_to_json b)]
  | FUnary (op, g) ->
      `Assoc [("type",    `String "FUnary");
              ("op",      `String (string_of_unary_op op));
              ("operand", formula_to_json g)]
  | FBinary (op, a, b) ->
      `Assoc [("type",  `String "FBinary");
              ("op",    `String (string_of_binary_op op));
              ("left",  formula_to_json a);
              ("right", formula_to_json b)]

let formula_to_json_string (f : formula) : string =
  Yojson.Safe.to_string (formula_to_json f)
