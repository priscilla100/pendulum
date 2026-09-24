
(* The type of tokens. *)

type token = 
  | YESTERDAY
  | WEAKUNTIL
  | UNTIL
  | TRUE
  | TRIGGER
  | SINCE
  | RPAREN
  | RELEASE
  | OR
  | ONCE
  | NOT
  | NEXT
  | LPAREN
  | IMPLIES
  | IFF
  | IDENT of (string)
  | HISTORICALLY
  | GLOBALLY
  | FALSE
  | EVENTUALLY
  | EOF
  | AND

(* This exception is raised by the monolithic API functions. *)

exception Error

(* The monolithic API. *)

val main: (Lexing.lexbuf -> token) -> Lexing.lexbuf -> (Ast.formula)

module MenhirInterpreter : sig
  
  (* The incremental API. *)
  
  include MenhirLib.IncrementalEngine.INCREMENTAL_ENGINE
    with type token = token
  
  (* The indexed type of terminal symbols. *)
  
  type _ terminal = 
    | T_error : unit terminal
    | T_YESTERDAY : unit terminal
    | T_WEAKUNTIL : unit terminal
    | T_UNTIL : unit terminal
    | T_TRUE : unit terminal
    | T_TRIGGER : unit terminal
    | T_SINCE : unit terminal
    | T_RPAREN : unit terminal
    | T_RELEASE : unit terminal
    | T_OR : unit terminal
    | T_ONCE : unit terminal
    | T_NOT : unit terminal
    | T_NEXT : unit terminal
    | T_LPAREN : unit terminal
    | T_IMPLIES : unit terminal
    | T_IFF : unit terminal
    | T_IDENT : (string) terminal
    | T_HISTORICALLY : unit terminal
    | T_GLOBALLY : unit terminal
    | T_FALSE : unit terminal
    | T_EVENTUALLY : unit terminal
    | T_EOF : unit terminal
    | T_AND : unit terminal
  
  (* The indexed type of nonterminal symbols. *)
  
  type _ nonterminal = 
    | N_main : (Ast.formula) nonterminal
    | N_formula : (Ast.formula) nonterminal
  
  (* The inspection API. *)
  
  include MenhirLib.IncrementalEngine.INSPECTION
    with type 'a lr1state := 'a lr1state
    with type production := production
    with type 'a terminal := 'a terminal
    with type 'a nonterminal := 'a nonterminal
    with type 'a env := 'a env
  
end

(* The entry point(s) to the incremental API. *)

module Incremental : sig
  
  val main: Lexing.position -> (Ast.formula) MenhirInterpreter.checkpoint
  
end
