--
-- SALT Compiler (translates SALT temporal specifications to LTL)
-- Copyright (C) 2006  Jonathan Streit
--
-- This program is free software; you can redistribute it and/or
-- modify it under the terms of the GNU General Public License
-- as published by the Free Software Foundation; either version 2
-- of the License, or (at your option) any later version.
--
-- This program is distributed in the hope that it will be useful,
-- but WITHOUT ANY WARRANTY; without even the implied warranty of
-- MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
-- GNU General Public License for more details.
--
-- You should have received a copy of the GNU General Public License
-- along with this program; if not, write to the Free Software
-- Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
-- 
-- See README for information on how to contact the author.
-- 

module SALT (Expr(..), getSI)where

-- This module defines the data structure for the syntax tree
-- in core SALT.
-- It also defines the required show functions.

import Common
import Timed

data Expr	= Ident SI String 
			| TT SI 
			| FF SI
			| Or SI Expr Expr 
			| And SI Expr Expr 
			| Not SI Expr 
			| Impl SI Expr Expr
			| Equ SI Expr Expr
			
			-- accept/reject operators
			| Reject SI Expr Expr
			| Accept SI Expr Expr 

			-- temporal operators
			| Until FP SI Expr Expr 
			| Next FP SI Expr 
			| Always FP SI Expr 
			| Eventually FP SI Expr 
				
			-- upto/from/between and related modifiers
			-- modifiers are implemented as unary macros			
			| UpTo FP SI Expr Expr 
			| From FP SI Expr Expr 
			| Between FP SI Expr Expr Expr
			| Required SI Expr
			| Optional SI Expr
			| Weak SI Expr
			| Inclusive SI Expr
			| Exclusive SI Expr
			
			-- sequence operators
			| RegExp FP SI Expr
			| Sequence FP SI Expr Expr
			| OverlapSequence FP SI Expr Expr
			| RepeatGreaterOrEqual FP SI Int Expr
			| EmptySequence FP SI 
			
			-- timed modifier
			| Timed SI TimeRange Expr 

			| Error SI String 
			
			deriving Eq
			
instance Show Expr where	
  show (Ident _ i) = i 
  show (TT _) = "true"
  show (FF _) = "false" 
  show (Or _ e1 e2) = "(" ++ (show e1) ++ " | " ++ (show e2) ++ ")"
  show (And _ e1 e2) = "(" ++ (show e1) ++ " & " ++ (show e2) ++ ")"
  show (Not _ e) = "!(" ++ (show e) ++ ")"
  show (Impl _ e1 e2) = "(" ++ (show e1) ++ " -> " ++ (show e2) ++ ")"
  show (Equ _ e1 e2) = "(" ++ (show e1) ++ " <-> " ++ (show e2) ++ ")"
			
  show (Reject _ e1 e2) = "(" ++ (show e1) ++ " rejecton " ++ (show e2) ++ ")"
  show (Accept _ e1 e2) = "(" ++ (show e1) ++ " accepton " ++ (show e2) ++ ")"

  show (Until fp _ e1 e2) = "(" ++ (show e1) ++ " until" ++ (show fp) ++ " " ++ (show e2) ++ ")"
  show (Next fp _ e) = "(next" ++ (show fp) ++ " " ++ (show e) ++ ")"
  show (Always fp _ e) = "(always" ++ (show fp) ++ " " ++ (show e) ++ ")"
  show (Eventually fp _ e) = "(eventually" ++ (show fp) ++ " " ++ (show e) ++ ")"
			
  show (UpTo fp _ e1 e2) = "(" ++ (show e1) ++ " upto" ++ (show fp) ++ " " ++ (show e2) ++ ")"
  show (From fp _ e1 e2) = "(" ++ (show e1) ++ " from" ++ (show fp) ++ " " ++ (show e2) ++ ")"
  show (Between fp _ e1 e2 e3) = "(" ++ (show e1) ++ " between" ++ (show fp) ++ " " ++ (show e2) ++ ", " ++ (show e3) ++ ")"
  show (Required _ e) = "required " ++ (show e)
  show (Optional _ e) = "optional " ++ (show e)
  show (Weak _ e) = "weak " ++ (show e)
  show (Inclusive _ e) = "inclusive " ++ (show e)
  show (Exclusive _ e) = "exclusive " ++ (show e)
			
  show (Sequence Future _ e1 e2) = (show e1) ++ "; " ++ (show e2)
  show (OverlapSequence Future _ e1 e2) = (show e1) ++ ": " ++ (show e2)
  show (RegExp Future _ e) = "/" ++ (show e) ++ "/"
  show (RegExp Past _ e) = "\\" ++ (show e) ++ "\\"
  show (RepeatGreaterOrEqual _ _ r e) = "(" ++ (show e) ++ ")*[>=" ++ (show r) ++ "]"
  show (EmptySequence Future _) = "//"
  show (EmptySequence Past _) = "\\\\"
			
  show (Timed _ r e) = "[" ++ (show r) ++ "] " ++ (show e) 

  show (Error si s) = "<ERROR: " ++ s ++ " at " ++ (show si) ++ ">"


-- Returns the source code position info contained in an expression
getSI :: Expr -> SI
getSI (Ident si i) = si
getSI (TT si) = si
getSI (FF si) = si
getSI (Or si _ _) = si
getSI (And si _ _) = si
getSI (Not si _) = si
getSI (Impl si _ _) = si
getSI (Equ si _ _) = si			
getSI (Reject si _ _) = si
getSI (Accept si _ _) = si
getSI (Until _ si _ _) = si
getSI (Next _ si _) = si
getSI (Always _ si _) = si
getSI (Eventually _ si _) = si						
getSI (UpTo _ si _ _) = si
getSI (From _ si _ _) = si
getSI (Between _ si _ _ _) = si
getSI (Required si _) = si
getSI (Optional si _) = si
getSI (Weak si _) = si
getSI (Inclusive si _) = si
getSI (Exclusive si _) = si
getSI (Sequence _ si _ _) = si
getSI (RegExp _ si _) = si
getSI (OverlapSequence _ si _ _) = si
getSI (RepeatGreaterOrEqual _ si n _) = si
getSI (EmptySequence _ si) = si
getSI (Timed si r _) = si
getSI (Error si s) = si


