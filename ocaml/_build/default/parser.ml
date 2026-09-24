
(* This generated code requires the following version of MenhirLib: *)

let () =
  MenhirLib.StaticVersion.require_20250912

module MenhirBasics = struct
  
  exception Error
  
  let _eRR =
    fun _s ->
      raise Error
  
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
    | IDENT of (
# 21 "parser.mly"
       (string)
# 35 "parser.ml"
  )
    | HISTORICALLY
    | GLOBALLY
    | FALSE
    | EVENTUALLY
    | EOF
    | AND
  
end

include MenhirBasics

# 16 "parser.mly"
  
  open Ast

# 52 "parser.ml"

module Tables = struct
  
  include MenhirBasics
  
  let token2terminal : token -> int =
    fun _tok ->
      match _tok with
      | AND ->
          22
      | EOF ->
          21
      | EVENTUALLY ->
          20
      | FALSE ->
          19
      | GLOBALLY ->
          18
      | HISTORICALLY ->
          17
      | IDENT _ ->
          16
      | IFF ->
          15
      | IMPLIES ->
          14
      | LPAREN ->
          13
      | NEXT ->
          12
      | NOT ->
          11
      | ONCE ->
          10
      | OR ->
          9
      | RELEASE ->
          8
      | RPAREN ->
          7
      | SINCE ->
          6
      | TRIGGER ->
          5
      | TRUE ->
          4
      | UNTIL ->
          3
      | WEAKUNTIL ->
          2
      | YESTERDAY ->
          1
  
  and error_terminal =
    0
  
  and token2value : token -> Obj.t =
    fun _tok ->
      match _tok with
      | AND ->
          Obj.repr ()
      | EOF ->
          Obj.repr ()
      | EVENTUALLY ->
          Obj.repr ()
      | FALSE ->
          Obj.repr ()
      | GLOBALLY ->
          Obj.repr ()
      | HISTORICALLY ->
          Obj.repr ()
      | IDENT _v ->
          Obj.repr (_v : (
# 21 "parser.mly"
       (string)
# 128 "parser.ml"
          ))
      | IFF ->
          Obj.repr ()
      | IMPLIES ->
          Obj.repr ()
      | LPAREN ->
          Obj.repr ()
      | NEXT ->
          Obj.repr ()
      | NOT ->
          Obj.repr ()
      | ONCE ->
          Obj.repr ()
      | OR ->
          Obj.repr ()
      | RELEASE ->
          Obj.repr ()
      | RPAREN ->
          Obj.repr ()
      | SINCE ->
          Obj.repr ()
      | TRIGGER ->
          Obj.repr ()
      | TRUE ->
          Obj.repr ()
      | UNTIL ->
          Obj.repr ()
      | WEAKUNTIL ->
          Obj.repr ()
      | YESTERDAY ->
          Obj.repr ()
  
  and default_reduction =
    (8, "\000\000\002\000\000\000\000\004\000\000\003\000\t\n\012\000\000\000\000\000\000\000\000\000\000\000\005\000\000\000\000\000\000\000\000\007\006\011\b\001\000\022")
  
  and error =
    (23, "H<\248\144y\240\000\000\002A\231\196\131\207\137\007\159\018\015>\000\000\000H<\248\144y\240\000\000\002A\231\192\000\000\000\000\000\000\000\000\027\225\129H<\248o\134\r \243\225\190\0244\131\207\134\248`\210\015>\027\225\131H<\248o\134\012\000\000\002A\231\195|0i\007\159\r\240\193\164\030|7\195\006\144y\240\223\012\024\000\000\000\000\000\000\000\000\000\000\000\000\000\0006\195\006\000\000\000")
  
  and start =
    1
  
  and action =
    ((16, "\001\148\001\148\000\000\001\148\001\148\001\148\001\148\000\000\001\148\001\148\000\000\001\148\000\000\000\000\000\000\000\005\001\148\000\248\001\148\000\206\001\148\000\164\001\148\000z\001\148\001v\000\000\001\148\000&\001\148\001L\001\148\001\"\001\148\000P\000\000\000\000\000\000\000\000\000\000\000\005\000\000"), (8, "BJ\000RZjbn\000\000\000\000~\134\000\000\000\000\000\167vBJ\000RZ5b5\000\000\000\00055\000\000\000\000\0005vBJ\000RZ=bn\000\000\000\000~\134\000\000\000\000\000=vBJ\000RZEbE\000\000\000\000EE\000\000\000\000\000EEBJ\000RZQbQ\000\000\000\000QQ\000\000\000\000\000QQBJ\000RZAbA\000\000\000\000AA\000\000\000\000\000AABJ\000RZIbI\000\000\000\000II\000\000\000\000\000IIBJ\000RZ9bn\000\000\000\000~9\000\000\000\000\0009vBJ\000RZ1b1\000\000\000\00011\000\000\000\000\00011BJ\000RZMbM\000\000\000\000MM\006\000\000\n\000MM\000\000\014\018\022\026\000\000\030\"&*."))
  
  and lhs =
    (2, "*\170\170\170\170\144")
  
  and goto =
    ((8, "\003\012\000\018\000\b\028\000\024 \000\002\000\000\000\000\014\000\006\000\016\000\030\000\022\000\000\026\000\004\000\020\000\n\000\000\000\000\000\000\000\000"), (8, "()%\r\031\020$#'\018\022&!\026\015\029\016\024\014"))
  
  and semantic_action =
    [|
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = _1;
          MenhirLib.EngineTypes.startp = _startpos__1_;
          MenhirLib.EngineTypes.endp = _endpos__1_;
          MenhirLib.EngineTypes.next = _menhir_stack;
        } = _menhir_stack in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos__1_ in
        let _v : (Ast.formula) = 
# 44 "parser.mly"
                                              ( FTrue )
# 197 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = _1;
          MenhirLib.EngineTypes.startp = _startpos__1_;
          MenhirLib.EngineTypes.endp = _endpos__1_;
          MenhirLib.EngineTypes.next = _menhir_stack;
        } = _menhir_stack in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos__1_ in
        let _v : (Ast.formula) = 
# 45 "parser.mly"
                                              ( FFalse )
# 222 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = id;
          MenhirLib.EngineTypes.startp = _startpos_id_;
          MenhirLib.EngineTypes.endp = _endpos_id_;
          MenhirLib.EngineTypes.next = _menhir_stack;
        } = _menhir_stack in
        let id : (
# 21 "parser.mly"
       (string)
# 243 "parser.ml"
        ) = Obj.magic id in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_id_ in
        let _endpos = _endpos_id_ in
        let _v : (Ast.formula) = 
# 46 "parser.mly"
                                              ( FAtom id )
# 251 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = _3;
          MenhirLib.EngineTypes.startp = _startpos__3_;
          MenhirLib.EngineTypes.endp = _endpos__3_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = f;
            MenhirLib.EngineTypes.startp = _startpos_f_;
            MenhirLib.EngineTypes.endp = _endpos_f_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = _1;
              MenhirLib.EngineTypes.startp = _startpos__1_;
              MenhirLib.EngineTypes.endp = _endpos__1_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let _3 : unit = Obj.magic _3 in
        let f : (Ast.formula) = Obj.magic f in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos__3_ in
        let _v : (Ast.formula) = 
# 47 "parser.mly"
                                              ( f )
# 290 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = f;
          MenhirLib.EngineTypes.startp = _startpos_f_;
          MenhirLib.EngineTypes.endp = _endpos_f_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _menhir_s;
            MenhirLib.EngineTypes.semv = _1;
            MenhirLib.EngineTypes.startp = _startpos__1_;
            MenhirLib.EngineTypes.endp = _endpos__1_;
            MenhirLib.EngineTypes.next = _menhir_stack;
          };
        } = _menhir_stack in
        let f : (Ast.formula) = Obj.magic f in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos_f_ in
        let _v : (Ast.formula) = 
# 51 "parser.mly"
                                              ( FNot f )
# 322 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = f;
          MenhirLib.EngineTypes.startp = _startpos_f_;
          MenhirLib.EngineTypes.endp = _endpos_f_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _menhir_s;
            MenhirLib.EngineTypes.semv = _1;
            MenhirLib.EngineTypes.startp = _startpos__1_;
            MenhirLib.EngineTypes.endp = _endpos__1_;
            MenhirLib.EngineTypes.next = _menhir_stack;
          };
        } = _menhir_stack in
        let f : (Ast.formula) = Obj.magic f in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos_f_ in
        let _v : (Ast.formula) = 
# 52 "parser.mly"
                                              ( FUnary (Next,         f) )
# 354 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = f;
          MenhirLib.EngineTypes.startp = _startpos_f_;
          MenhirLib.EngineTypes.endp = _endpos_f_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _menhir_s;
            MenhirLib.EngineTypes.semv = _1;
            MenhirLib.EngineTypes.startp = _startpos__1_;
            MenhirLib.EngineTypes.endp = _endpos__1_;
            MenhirLib.EngineTypes.next = _menhir_stack;
          };
        } = _menhir_stack in
        let f : (Ast.formula) = Obj.magic f in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos_f_ in
        let _v : (Ast.formula) = 
# 53 "parser.mly"
                                              ( FUnary (Yesterday,    f) )
# 386 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = f;
          MenhirLib.EngineTypes.startp = _startpos_f_;
          MenhirLib.EngineTypes.endp = _endpos_f_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _menhir_s;
            MenhirLib.EngineTypes.semv = _1;
            MenhirLib.EngineTypes.startp = _startpos__1_;
            MenhirLib.EngineTypes.endp = _endpos__1_;
            MenhirLib.EngineTypes.next = _menhir_stack;
          };
        } = _menhir_stack in
        let f : (Ast.formula) = Obj.magic f in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos_f_ in
        let _v : (Ast.formula) = 
# 54 "parser.mly"
                                              ( FUnary (Eventually,   f) )
# 418 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = f;
          MenhirLib.EngineTypes.startp = _startpos_f_;
          MenhirLib.EngineTypes.endp = _endpos_f_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _menhir_s;
            MenhirLib.EngineTypes.semv = _1;
            MenhirLib.EngineTypes.startp = _startpos__1_;
            MenhirLib.EngineTypes.endp = _endpos__1_;
            MenhirLib.EngineTypes.next = _menhir_stack;
          };
        } = _menhir_stack in
        let f : (Ast.formula) = Obj.magic f in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos_f_ in
        let _v : (Ast.formula) = 
# 55 "parser.mly"
                                              ( FUnary (Globally,     f) )
# 450 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = f;
          MenhirLib.EngineTypes.startp = _startpos_f_;
          MenhirLib.EngineTypes.endp = _endpos_f_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _menhir_s;
            MenhirLib.EngineTypes.semv = _1;
            MenhirLib.EngineTypes.startp = _startpos__1_;
            MenhirLib.EngineTypes.endp = _endpos__1_;
            MenhirLib.EngineTypes.next = _menhir_stack;
          };
        } = _menhir_stack in
        let f : (Ast.formula) = Obj.magic f in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos_f_ in
        let _v : (Ast.formula) = 
# 56 "parser.mly"
                                              ( FUnary (Once,         f) )
# 482 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = f;
          MenhirLib.EngineTypes.startp = _startpos_f_;
          MenhirLib.EngineTypes.endp = _endpos_f_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _menhir_s;
            MenhirLib.EngineTypes.semv = _1;
            MenhirLib.EngineTypes.startp = _startpos__1_;
            MenhirLib.EngineTypes.endp = _endpos__1_;
            MenhirLib.EngineTypes.next = _menhir_stack;
          };
        } = _menhir_stack in
        let f : (Ast.formula) = Obj.magic f in
        let _1 : unit = Obj.magic _1 in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos__1_ in
        let _endpos = _endpos_f_ in
        let _v : (Ast.formula) = 
# 57 "parser.mly"
                                              ( FUnary (Historically, f) )
# 514 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 60 "parser.mly"
                                              ( FAnd     (a, b) )
# 553 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 61 "parser.mly"
                                              ( FOr      (a, b) )
# 592 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 62 "parser.mly"
                                              ( FImplies (a, b) )
# 631 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 63 "parser.mly"
                                              ( FIff     (a, b) )
# 670 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 66 "parser.mly"
                                              ( FBinary (Until,     a, b) )
# 709 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 67 "parser.mly"
                                              ( FBinary (Since,     a, b) )
# 748 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 68 "parser.mly"
                                              ( FBinary (WeakUntil, a, b) )
# 787 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 69 "parser.mly"
                                              ( FBinary (Release,   a, b) )
# 826 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = b;
          MenhirLib.EngineTypes.startp = _startpos_b_;
          MenhirLib.EngineTypes.endp = _endpos_b_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _;
            MenhirLib.EngineTypes.semv = _2;
            MenhirLib.EngineTypes.startp = _startpos__2_;
            MenhirLib.EngineTypes.endp = _endpos__2_;
            MenhirLib.EngineTypes.next = {
              MenhirLib.EngineTypes.state = _menhir_s;
              MenhirLib.EngineTypes.semv = a;
              MenhirLib.EngineTypes.startp = _startpos_a_;
              MenhirLib.EngineTypes.endp = _endpos_a_;
              MenhirLib.EngineTypes.next = _menhir_stack;
            };
          };
        } = _menhir_stack in
        let b : (Ast.formula) = Obj.magic b in
        let _2 : unit = Obj.magic _2 in
        let a : (Ast.formula) = Obj.magic a in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_a_ in
        let _endpos = _endpos_b_ in
        let _v : (Ast.formula) = 
# 70 "parser.mly"
                                              ( FBinary (Trigger,   a, b) )
# 865 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
      (fun _menhir_env ->
        let _menhir_stack = _menhir_env.MenhirLib.EngineTypes.stack in
        let {
          MenhirLib.EngineTypes.state = _;
          MenhirLib.EngineTypes.semv = _2;
          MenhirLib.EngineTypes.startp = _startpos__2_;
          MenhirLib.EngineTypes.endp = _endpos__2_;
          MenhirLib.EngineTypes.next = {
            MenhirLib.EngineTypes.state = _menhir_s;
            MenhirLib.EngineTypes.semv = f;
            MenhirLib.EngineTypes.startp = _startpos_f_;
            MenhirLib.EngineTypes.endp = _endpos_f_;
            MenhirLib.EngineTypes.next = _menhir_stack;
          };
        } = _menhir_stack in
        let _2 : unit = Obj.magic _2 in
        let f : (Ast.formula) = Obj.magic f in
        let _endpos__0_ = _menhir_stack.MenhirLib.EngineTypes.endp in
        let _startpos = _startpos_f_ in
        let _endpos = _endpos__2_ in
        let _v : (Ast.formula) = 
# 41 "parser.mly"
                                              ( f )
# 897 "parser.ml"
         in
        {
          MenhirLib.EngineTypes.state = _menhir_s;
          MenhirLib.EngineTypes.semv = Obj.repr _v;
          MenhirLib.EngineTypes.startp = _startpos;
          MenhirLib.EngineTypes.endp = _endpos;
          MenhirLib.EngineTypes.next = _menhir_stack;
        });
    |]
  
  and trace =
    None
  
end

module MenhirInterpreter = struct
  
  module ET = MenhirLib.TableInterpreter.MakeEngineTable (Tables)
  
  module TI = MenhirLib.Engine.Make (ET)
  
  include TI
  
  module Symbols = struct
    
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
      | T_IDENT : (
# 21 "parser.mly"
       (string)
# 943 "parser.ml"
    ) terminal
      | T_HISTORICALLY : unit terminal
      | T_GLOBALLY : unit terminal
      | T_FALSE : unit terminal
      | T_EVENTUALLY : unit terminal
      | T_EOF : unit terminal
      | T_AND : unit terminal
    
    type _ nonterminal = 
      | N_main : (Ast.formula) nonterminal
      | N_formula : (Ast.formula) nonterminal
    
  end
  
  include Symbols
  
  include MenhirLib.InspectionTableInterpreter.Make (Tables) (struct
    
    include TI
    
    include Symbols
    
    include MenhirLib.InspectionTableInterpreter.Symbols (Symbols)
    
    let terminal =
      fun t ->
        match t with
        | 0 ->
            X (T T_error)
        | 1 ->
            X (T T_YESTERDAY)
        | 2 ->
            X (T T_WEAKUNTIL)
        | 3 ->
            X (T T_UNTIL)
        | 4 ->
            X (T T_TRUE)
        | 5 ->
            X (T T_TRIGGER)
        | 6 ->
            X (T T_SINCE)
        | 7 ->
            X (T T_RPAREN)
        | 8 ->
            X (T T_RELEASE)
        | 9 ->
            X (T T_OR)
        | 10 ->
            X (T T_ONCE)
        | 11 ->
            X (T T_NOT)
        | 12 ->
            X (T T_NEXT)
        | 13 ->
            X (T T_LPAREN)
        | 14 ->
            X (T T_IMPLIES)
        | 15 ->
            X (T T_IFF)
        | 16 ->
            X (T T_IDENT)
        | 17 ->
            X (T T_HISTORICALLY)
        | 18 ->
            X (T T_GLOBALLY)
        | 19 ->
            X (T T_FALSE)
        | 20 ->
            X (T T_EVENTUALLY)
        | 21 ->
            X (T T_EOF)
        | 22 ->
            X (T T_AND)
        | _ ->
            assert false
    
    and nonterminal =
      fun nt ->
        match nt with
        | 2 ->
            X (N N_formula)
        | 1 ->
            X (N N_main)
        | _ ->
            assert false
    
    and lr0_incoming =
      (8, "\000\004\n\022\024\026\028\"$&(*\005\006\005\b\005\012\005\014\005\018\005\020\005\030\005 \005.\005\005\005\005\016\005\005\005\005\003\005,")
    
    and rhs =
      ((8, "\003\n(\"\028\005\016\024\005\026\005\004\005*\005&\005\022\005$\005\005.\005\005\020\005\005\030\005\005 \005\005\b\005\005\014\005\005\006\005\005\018\005\005\012\005\005,"), (8, "\000\001\002\003\004\007\t\011\r\015\017\019\021\024\027\030!$'*-02"))
    
    and lr0_core =
      (8, "\000\001\002\003\004\005\006\007\b\t\n\011\012\031 !\r\014\015\016\017\018\019\020\021\022\"\023\024\029\030\025\026\027\028#$%&'()")
    
    and lr0_items =
      ((16, "\000\000\028\001\004\001(\001\020\001\024\001\016\001\012\001,\001$\001\b\001 \001P\001L\001H\001D\001@\001<\0018\0014\0010\001 \002H\002P\001L\001H\003H\001D\001@\001<\0018\0014\0010\001@\002P\001L\001H\001D\001@\003@\001<\0018\0014\0010\001P\002P\003P\001L\001H\001D\001@\001<\0018\0014\0010\001D\002P\001L\001H\001D\003D\001@\001<\0018\0014\0010\001L\002P\001L\003L\001H\001D\001@\001<\0018\0014\0010\0014\002P\001L\001H\001D\001@\001<\0018\0014\0034\0010\0018\002P\001L\001H\001D\001@\001<\0018\0038\0014\0010\001<\002P\001L\001H\001D\001@\001<\003<\0018\0014\0010\0010\002P\001L\001H\001D\001@\001<\0018\0014\0010\0030\001P\001L\001H\001D\001@\001<\0018\0014\0010\001$\002P\001L\001H\001D\001@\001<\0018\0014\0010\001,\002P\001L\001H\001D\001@\001<\0018\0014\0010\001\016\002\016\003P\001L\001H\001D\001@\001<\0018\0014\0010\001\024\002P\001L\001H\001D\001@\001<\0018\0014\0010\001\020\002P\001L\001H\001D\001@\001<\0018\0014\0010\001(\002P\001L\001H\001D\001@\001<\0018\0014\0010\001\028\002\000\001T\001P\001L\001H\001D\001@\001<\0018\0014\0010\001T\002"), (8, "\000\001\002\003\004\005\006\007\b\t\n\011\012\022\023!\",-78BCMNXYcdnoy\131\141\151\152\162\172\182\192\193\203\204"))
    
    and nullable =
      "\000"
    
    and first =
      (23, "H<\248\144y\241 \243\224")
    
  end) (ET) (TI)
  
end

let main =
  fun lexer lexbuf : (Ast.formula) ->
    Obj.magic (MenhirInterpreter.entry `Legacy 0 lexer lexbuf)

module Incremental = struct
  
  let main =
    fun initial_position : (Ast.formula) MenhirInterpreter.checkpoint ->
      Obj.magic (MenhirInterpreter.start 0 initial_position)
  
end
