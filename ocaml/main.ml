(** CLI front-end for the PLTL parser.

    Two output modes:
      - default: parse and pretty-print, with a short banner;
      - [--json]: emit the AST as JSON (the wire format consumed by the
        Rust back-end). With [--output FILE], the JSON is written to FILE
        instead of stdout. *)

open Pltl

let parse_string s =
  let lexbuf = Lexing.from_string s in
  try Parser.main Lexer.token lexbuf with
  | Lexer.Lexical_error msg ->
      Printf.eprintf "Lexical error: %s\n" msg;
      exit 1
  | Parser.Error ->
      let pos = Lexing.lexeme_start_p lexbuf in
      Printf.eprintf "Parse error at column %d\n"
        (pos.pos_cnum - pos.pos_bol);
      exit 1

(* Tiny inline argv scanner. Kept simple because the CLI has only two
   options and pulling in a flag library would be overkill. *)
let find_flag flag argv =
  let n = Array.length argv in
  let rec loop i =
    if i >= n then None
    else if argv.(i) = flag then Some i
    else loop (i + 1)
  in
  loop 0

let () =
  if Array.length Sys.argv < 2 then begin
    Printf.eprintf "Usage: %s '<formula>' [--json] [--output <file>]\n"
      Sys.argv.(0);
    exit 1
  end;

  let input = Sys.argv.(1) in
  let use_json = find_flag "--json" Sys.argv <> None in
  let output_file =
    match find_flag "--output" Sys.argv with
    | Some i when i + 1 < Array.length Sys.argv -> Some Sys.argv.(i + 1)
    | _ -> None
  in

  let ast = parse_string input in

  if use_json then begin
    let json = Ast.formula_to_json_string ast in
    match output_file with
    | Some filename ->
        let oc = open_out filename in
        output_string oc json;
        close_out oc
    | None ->
        print_endline json
  end else begin
    Printf.printf "Parsing: %s\n\n" input;
    Printf.printf "AST:\n%s\n\n" (Ast.string_of_formula ast);
    Printf.printf "Success!\n"
  end
