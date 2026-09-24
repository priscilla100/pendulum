(* Menhir grammar for PLTL formulas.

   Precedence (low → high; ties resolved by associativity):

       <->                                   right-associative
       ->                                    right-associative
       |                                     left-associative
       &                                     left-associative
       U  S  W  R  T   (binary temporal)     right-associative
       !  X  Y  F  G  O  H   (unary prefix)  bind tightest

   The unary tokens are listed last in the %nonassoc declaration so that
   any production whose rightmost terminal is a unary connective inherits
   the highest precedence — making "G p & q" parse as "(G p) & q". *)

%{
  open Ast
%}

%token TRUE FALSE
%token <string> IDENT
%token LPAREN RPAREN
%token NOT
%token AND OR IMPLIES IFF
%token NEXT YESTERDAY EVENTUALLY GLOBALLY ONCE HISTORICALLY
%token UNTIL SINCE WEAKUNTIL RELEASE TRIGGER
%token EOF

%right IFF
%right IMPLIES
%left  OR
%left  AND
%right UNTIL SINCE WEAKUNTIL RELEASE TRIGGER
%nonassoc NOT NEXT YESTERDAY EVENTUALLY GLOBALLY ONCE HISTORICALLY

%start <Ast.formula> main

%%

main:
  | f = formula; EOF                          { f }

formula:
  | TRUE                                      { FTrue }
  | FALSE                                     { FFalse }
  | id = IDENT                                { FAtom id }
  | LPAREN; f = formula; RPAREN               { f }

  (* Unary prefix operators. All share the tightest precedence level so
     that e.g. "G F p" parses as "G (F p)" and "!p & q" as "(!p) & q". *)
  | NOT;          f = formula                 { FNot f }
  | NEXT;         f = formula                 { FUnary (Next,         f) }
  | YESTERDAY;    f = formula                 { FUnary (Yesterday,    f) }
  | EVENTUALLY;   f = formula                 { FUnary (Eventually,   f) }
  | GLOBALLY;     f = formula                 { FUnary (Globally,     f) }
  | ONCE;         f = formula                 { FUnary (Once,         f) }
  | HISTORICALLY; f = formula                 { FUnary (Historically, f) }

  (* Logical connectives. *)
  | a = formula; AND;       b = formula       { FAnd     (a, b) }
  | a = formula; OR;        b = formula       { FOr      (a, b) }
  | a = formula; IMPLIES;   b = formula       { FImplies (a, b) }
  | a = formula; IFF;       b = formula       { FIff     (a, b) }

  (* Binary temporal connectives. *)
  | a = formula; UNTIL;     b = formula       { FBinary (Until,     a, b) }
  | a = formula; SINCE;     b = formula       { FBinary (Since,     a, b) }
  | a = formula; WEAKUNTIL; b = formula       { FBinary (WeakUntil, a, b) }
  | a = formula; RELEASE;   b = formula       { FBinary (Release,   a, b) }
  | a = formula; TRIGGER;   b = formula       { FBinary (Trigger,   a, b) }
