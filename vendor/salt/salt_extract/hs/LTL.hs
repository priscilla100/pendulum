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

module LTL (Expr (..), getSI) where

-- This module defines the data structure for the syntax tree
-- in LTL. This still includes WeakUntil and Releases, which may be
-- replaced during output.
-- It also defines the required show functions.

import Common
import Timed

data Expr 	= Ident SI String 
			| TT SI
			| FF SI
			| Or SI Expr Expr 
			| And SI Expr Expr 
			| Not SI Expr 			
			| Impl SI Expr Expr
			| Equ SI Expr Expr
			
			-- temporal operators
			| Until FP SI Expr Expr 
			| WeakUntil FP SI Expr Expr 
			| Next FP SI Expr 
			| Always FP SI Expr 
			| Eventually FP SI Expr 
			
			-- timed operators
			| TPredict FP SI TimeRange Expr
			| TUntil FP SI TimeRange Expr Expr 
			| TWeakUntil FP SI TimeRange Expr Expr 
			| TAlways FP SI TimeRange Expr
			| TEventually FP SI TimeRange Expr
			
			| Error SI String
			
			deriving Eq

			
instance Show Expr where	
  show (Ident _ i) = i 
  show (TT _) = "1"
  show (FF _) = "0" 
  show (Or _ e1 e2) = "(" ++ (show e1) ++ " | " ++ (show e2) ++ ")"
  show (And _ e1 e2) = "(" ++ (show e1) ++ " & " ++ (show e2) ++ ")"
  show (Not _ e) = "!(" ++ (show e) ++ ")"
  show (Impl _ e1 e2) = "(" ++ (show e1) ++ " -> " ++ (show e2) ++ ")"
  show (Equ _ e1 e2) = "(" ++ (show e1) ++ " <-> " ++ (show e2) ++ ")"
			
  show (Until Future _ e1 e2) = "(" ++ (show e1) ++ " U " ++ (show e2) ++ ")"
  show (WeakUntil Future _ e1 e2) = "(" ++ (show e1) ++ " W "  ++ (show e2) ++ ")"
  show (Next Future _ e) = "(X " ++ (show e) ++ ")"
  show (Always Future _ e) = "(G " ++ (show e) ++ ")"
  show (Eventually Future _ e) = "(F " ++ (show e) ++ ")"
						
  show (Until Past _ e1 e2) = "(" ++ (show e1) ++ " S " ++ (show e2) ++ ")"
  show (WeakUntil Past _ e1 e2) = "(" ++ (show e1) ++ " WS "  ++ (show e2) ++ ")"
  show (Next Past _ e) = "(Y " ++ (show e) ++ ")"
  show (Always Past _ e) = "(H " ++ (show e) ++ ")"
  show (Eventually Past _ e) = "(O " ++ (show e) ++ ")"
 
  show (TUntil Future _ r e1 e2) = "(" ++ (show e1) ++ " U " ++ " [" ++ (show r) ++ "] " ++ (show e2) ++ ")"
  show (TWeakUntil Future _ r e1 e2) = "(" ++ (show e1) ++ " W "  ++ " [" ++ (show r) ++ "] " ++ (show e2) ++ ")"
  show (TPredict Future _ r e) = "(X [" ++ (show r) ++ "] " ++ (show e) ++ ")"
  show (TAlways Future _ r e) = "(G [" ++ (show r) ++ "] " ++ (show e) ++ ")"
  show (TEventually Future _ r e) = "(F [" ++ (show r) ++ "] " ++ (show e) ++ ")"

  show (TUntil Past _ r e1 e2) = "(" ++ (show e1) ++ " S " ++ " [" ++ (show r) ++ "] " ++ (show e2) ++ ")"
  show (TWeakUntil Past _ r e1 e2) = "(" ++ (show e1) ++ " WS "  ++ " [" ++ (show r) ++ "] " ++ (show e2) ++ ")"
  show (TPredict Past _ r e) = "(Y [" ++ (show r) ++ "] " ++ (show e) ++ ")"
  show (TAlways Past _ r e) = "(H [" ++ (show r) ++ "] " ++ (show e) ++ ")"
  show (TEventually Past _ r e) = "(O [" ++ (show r) ++ "] " ++ (show e) ++ ")"

  show (Error si s) = "<ERROR: " ++ s ++ " at " ++ (show si) ++ ">"

-- Returns the source code position info contained in an expression
getSI :: Expr -> SI
getSI (Ident si _) = si
getSI (TT si) = si
getSI (FF si) = si
getSI (Or si _ _) = si
getSI (And si _ _) = si
getSI (Not si _) = si
getSI (Impl si _ _) = si
getSI (Equ si _ _) = si			
getSI (Until _ si _ _) = si
getSI (WeakUntil _ si _ _) = si
getSI (Next _ si _) = si
getSI (Always _ si _) = si
getSI (Eventually _ si _) = si						
getSI (TPredict _ si r _) = si						
getSI (TUntil _ si r _ _) = si
getSI (TWeakUntil _ si r _ _) = si
getSI (TAlways _ si r _) = si						
getSI (TEventually _ si r _) = si						
getSI (Error si s) = si

