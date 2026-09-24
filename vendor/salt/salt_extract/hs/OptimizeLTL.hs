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

module OptimizeLTL (optimizeLTL, simplifyExpr,
  replaceWeakUntilByUntil, replaceWeakUntilByBest, 
  replaceAlways, replaceEventually, 
  replaceTUntilByTPredict, replaceTWeakUntilByBest,
  replaceTWeakUntilForOutput,
  replaceTAlwaysByTPredict, replaceTEventuallyByTPredict) where

-- This module defines various functions for replacing operators
-- (replaceXXX) and for optimizing a formula in LTL a little bit.
-- Furthermore it supplies checkConstraints that allows
-- to check for violation of constraints on a formula,
-- like the occurrence of past operators

import LTL
import Common
import Timed

-- Do various optimizations on a formula
optimizeLTL :: Expr -> Expr
optimizeLTL e = repeatSimplifyExpr e

-- Helper function needed for best replacement of weak until
-- Size of a formula is estimated by number of temporal operators.
estimateSize :: Expr -> Int
estimateSize (Not _ e) = estimateSize e
estimateSize (Ident _ i) = 0
estimateSize (FF _) = 0
estimateSize (TT _) = 0
estimateSize (Eventually _ _ e) = 1 + (estimateSize e)
estimateSize (Always _ _ e) = 1 + (estimateSize e)
estimateSize (Next _ _ e) = 1 + (estimateSize e)
estimateSize (Until _ _ a1 a2) = 1 + (estimateSize a1) + (estimateSize a2)
estimateSize (WeakUntil _ _ a1 a2) = 1 + (estimateSize a1) + (estimateSize a2)
estimateSize (Or _ a1 a2) = (estimateSize a1) + (estimateSize a2)
estimateSize (And _ a1 a2) = (estimateSize a1) + (estimateSize a2)
estimateSize (Equ _ a1 a2) = (estimateSize a1) + (estimateSize a2)
estimateSize (Impl _ a1 a2) = (estimateSize a1) + (estimateSize a2)
estimateSize (TPredict _ _ r e) = 1 + (estimateSize e)
estimateSize (TUntil _ _ r e1 e2) = 1 + (estimateSize e1) + (estimateSize e2)
estimateSize (TWeakUntil _ _ r e1 e2) = 1 + (estimateSize e1) + (estimateSize e2)
estimateSize (TAlways _ _ r e) = 1 + (estimateSize e)
estimateSize (TEventually _ _ r e) = 1 + (estimateSize e)
estimateSize (Error _ s) = 0

replaceWeakUntilByUntil :: FP -> SI -> Expr -> Expr -> Expr
replaceWeakUntilByUntil fp si u1 u2 =
  (LTL.Not si (LTL.Until fp si (LTL.Not si u2) (LTL.And si (LTL.Not si u1) (LTL.Not si u2))))

replaceWeakUntilByUntilAlways :: FP -> SI -> Expr -> Expr -> Expr
replaceWeakUntilByUntilAlways fp si u1 u2 =
  (LTL.Or si (LTL.Until fp si u1 u2) (LTL.Always fp si u1))

replaceWeakUntilByBest :: FP -> SI -> Expr -> Expr -> Expr
replaceWeakUntilByBest fp si u1 u2 = 
  if ((estimateSize u1) < (estimateSize u2)) then replaceWeakUntilByUntilAlways fp si u1 u2
  else replaceWeakUntilByUntil fp si u1 u2

replaceAlways :: FP -> SI-> Expr -> Expr
replaceAlways fp si e = Not si (Until fp si (TT si) (Not si e))

replaceEventually :: FP -> SI -> Expr -> Expr
replaceEventually fp si e = Until fp si (TT si) e

replaceTUntilByTPredict :: FP -> SI -> TimeRange -> Expr -> Expr -> Expr
replaceTUntilByTPredict fp _ (TimeExactly si t) e1 e2 =
  Error si "timed with = may only be used in connection with next or nextinpast"
replaceTUntilByTPredict fp _ (TimeGreater si t) e1 e2 =
  Error si "timed with > may only be used in connection with next or nextinpast"
replaceTUntilByTPredict fp _ (TimeGreaterOrEqual si t) e1 e2 =
  Error si "timed with >= may only be used in connection with next or nextinpast"
replaceTUntilByTPredict fp si r (TT _) e2 =
    (Or si e2 (TPredict fp si r e2))
replaceTUntilByTPredict fp si r e1 e2 =
  And si
    (Until fp si e1 e2)
    (Or si e2 (TPredict fp si r e2))

-- This function replaces TWeakUntil and keeps all operators
-- timed, in contrast to replaceTWeakUntilForOutput that might
-- generate an untimed until.
replaceTWeakUntilByBest :: FP -> SI -> TimeRange -> Expr -> Expr -> Expr
replaceTWeakUntilByBest fp si (TimeExactly si2 t) e1 e2 =
  Error si "timed with = may only be used in connection with next or nextinpast"
replaceTWeakUntilByBest fp si (TimeGreaterOrEqual si2 t) e1 e2 =
  Error si "timed with >= may only be used in connection with next or nextinpast"
replaceTWeakUntilByBest fp si (TimeGreater si2 t) e1 e2 =
  Error si "timed with > may only be used in connection with next or nextinpast"
replaceTWeakUntilByBest fp si r e1 e2 =
  if ((estimateSize e1) < (estimateSize e2)) then 
    Or si
    (TUntil fp si r e1 e2)
    (TAlways fp si r e1)
  else 
    Not si
      (TUntil fp si r (Not si e2)
        (And si (Not si e1) (Not si e2)))

replaceTWeakUntilForOutput :: FP -> SI -> TimeRange -> Expr -> Expr -> Expr
replaceTWeakUntilForOutput fp si (TimeExactly si2 t) e1 e2 =
  Error si "timed with = may only be used in connection with next or nextinpast"
replaceTWeakUntilForOutput fp si (TimeGreaterOrEqual si2 t) e1 e2 =
  Error si "timed with >= may only be used in connection with next or nextinpast"
replaceTWeakUntilForOutput fp si (TimeGreater si2 t) e1 e2 =
  Error si "timed with > may only be used in connection with next or nextinpast"
replaceTWeakUntilForOutput fp si r e1 e2 =
  if ((estimateSize e1) < (estimateSize e2)) then 
  Or si
    (Until fp si e1 e2)
    (TAlways fp si r e1)
  else 
    Not si
      (TUntil fp si r (Not si e2)
        (And si (Not si e1) (Not si e2)))

replaceTAlwaysByTPredict :: FP -> SI-> TimeRange -> Expr -> Expr
replaceTAlwaysByTPredict fp _ (TimeExactly si t) e =
  Error si "timed with = may only be used in connection with next or nextinpast"
replaceTAlwaysByTPredict fp _ (TimeGreater si t) e =
  Error si "timed with > may only be used in connection with next or nextinpast"
replaceTAlwaysByTPredict fp _ (TimeGreaterOrEqual si t) e =
  Error si "timed with >= may only be used in connection with next or nextinpast"
replaceTAlwaysByTPredict fp si r e = And si e (Not si (TPredict fp si r (Not si e)))

replaceTEventuallyByTPredict :: FP -> SI -> TimeRange -> Expr -> Expr
replaceTEventuallyByTPredict fp _ (TimeExactly si t) e =
  Error si "timed with = may only be used in connection with next or nextinpast"
replaceTEventuallyByTPredict fp _ (TimeGreater si t) e =
  Error si "timed with > may only be used in connection with next or nextinpast"
replaceTEventuallyByTPredict fp _ (TimeGreaterOrEqual si t) e =
  Error si "timed with >= may only be used in connection with next or nextinpast"
replaceTEventuallyByTPredict fp si r e = Or si e (TPredict fp si r e)

-- Fixpoint iteration: repeat until there is no more simplification
-- possible
repeatSimplifyExpr :: Expr -> Expr
repeatSimplifyExpr e =
  let simplE = simplifyExpr e in
    if (simplE == e) then e
    else repeatSimplifyExpr simplE

-- Do one simplification run over a formula
-- Boolean operators, remove superfluous operators.
simplifyExpr :: Expr -> Expr
simplifyExpr (Not _ (Not _ e)) = simplifyExpr e
simplifyExpr (Not si (TT _)) = (FF si)
simplifyExpr (Not si (FF _)) = (TT si)
simplifyExpr (Or si (TT _) a2) = (TT si)
simplifyExpr (Or si a1 (TT _)) = (TT si)
simplifyExpr (Or si (FF _) a2) = simplifyExpr a2
simplifyExpr (Or si a1 (FF _)) = simplifyExpr a1
simplifyExpr (And si (TT _) a2) = simplifyExpr a2
simplifyExpr (And si a1 (TT _)) = simplifyExpr a1
simplifyExpr (And si (FF _) a2) = FF si
simplifyExpr (And si a1 (FF _)) = FF si
simplifyExpr (Equ si (TT _) a2) = simplifyExpr a2
simplifyExpr (Equ si a1 (TT _)) = simplifyExpr a1
simplifyExpr (Equ si (FF _) a2) = Not si (simplifyExpr a2)
simplifyExpr (Equ si a1 (FF _)) = Not si (simplifyExpr a1)
simplifyExpr (Impl si (TT _) a2) = simplifyExpr a2
simplifyExpr (Impl si a1 (TT _)) = TT si
simplifyExpr (Impl si (FF _) a2) = TT si
simplifyExpr (Impl si a1 (FF _)) = Not si (simplifyExpr a1)

-- Find expressions that can be made into eventually or always
simplifyExpr (Until fp si (TT _) e) = Eventually fp si e
simplifyExpr (Not _ (Eventually fp si (Not _ e))) = Always fp si e
simplifyExpr (TUntil fp si r (TT _) e) = TEventually fp si r e
simplifyExpr (Not _ (TEventually fp si r (Not _ e))) = TAlways fp si r e

-- a weakuntil a & b => !(!b until !a)
simplifyExpr (WeakUntil fp si e1 (And si2 e2 e3)) =
  if (e1 == e2) then
    Not si (Until fp si (Not si e3) (Not si e1))
  else if (e1 == e3) then
    Not si (Until fp si (Not si e2) (Not si e1))
  else (WeakUntil fp si (simplifyExpr e1) (simplifyExpr (And si2 e2 e3)))

-- e1 | e2 until e2 => e1 until e2
simplifyExpr (Until fp si (Or si2 e1 e2) e3) =
  if (e1 == e3) then (Until fp si e2 e3)
  else if (e2 == e3) then (Until fp si e1 e3)
  else (Until fp si (simplifyExpr (Or si2 e1 e2)) (simplifyExpr e3))
simplifyExpr (WeakUntil fp si (Or si2 e1 e2) e3) =
  if (e1 == e3) then (WeakUntil fp si e2 e3)
  else if (e2 == e3) then (WeakUntil fp si e1 e3)
  else (WeakUntil fp si (simplifyExpr (Or si2 e1 e2)) (simplifyExpr e3))
simplifyExpr (TUntil fp si r (Or si2 e1 e2) e3) =
  if (e1 == e3) then (TUntil fp si r e2 e3)
  else if (e2 == e3) then (TUntil fp si r e1 e3)
  else (TUntil fp si r (simplifyExpr (Or si2 e1 e2)) (simplifyExpr e3))
simplifyExpr (TWeakUntil fp si r (Or si2 e1 e2) e3) =
  if (e1 == e3) then (TWeakUntil fp si r e2 e3)
  else if (e2 == e3) then (TWeakUntil fp si r e1 e3)
  else (TWeakUntil fp si r (simplifyExpr (Or si2 e1 e2)) (simplifyExpr e3))

-- Remove consecutive always and eventually
-- always always e => always e
simplifyExpr (Always Future si (Always Future _ e)) = (Always Future si e)
simplifyExpr (Always Past si (Always Past _ e)) = (Always Past si e)
-- eventually eventually e => eventually e
simplifyExpr (Eventually Future si (Eventually Future _ e)) = (Eventually Future si e)
simplifyExpr (Eventually Past si (Eventually Past _ e)) = (Eventually Past si e)

-- Change !e until e into eventually
-- !e until e => eventually e
simplifyExpr (Until fp si (Not si2 e1) e2) = 
  if (e1 ==  e2) then Eventually fp si (simplifyExpr e2)
        else (Until fp si (simplifyExpr (Not si2 e1)) (simplifyExpr e2))
simplifyExpr (Until fp si e1 (Not si2 e2)) = 
  if (e1 == e2) then Eventually fp si (simplifyExpr (Not si2 e2))
        else (Until fp si (simplifyExpr e1) (simplifyExpr (Not si2 e2)))

-- Replace a pattern that occurs quite often and makes big automata:
-- always (a weakuntil b) => always (a | b)
simplifyExpr (Always Future si (WeakUntil Future si2 e1 e2)) = 
  (Always Future si (Or si2 (simplifyExpr e1) (simplifyExpr e2)))
simplifyExpr (Always Past si (WeakUntil Past si2 e1 e2)) = 
  (Always Past si (Or si2 (simplifyExpr e1) (simplifyExpr e2)))

-- other operators
simplifyExpr (Not si e) = Not si (simplifyExpr e)
simplifyExpr (Ident si i) = Ident si i
simplifyExpr (FF si) = FF si
simplifyExpr (TT si) = TT si
simplifyExpr (Eventually fp si e) = Eventually fp si (simplifyExpr e)
simplifyExpr (Always fp si e) = Always fp si (simplifyExpr e)
simplifyExpr (Next fp si e) = Next fp si (simplifyExpr e)
simplifyExpr (Until fp si a1 a2) = Until fp si (simplifyExpr a1) (simplifyExpr a2)
simplifyExpr (WeakUntil fp si a1 a2) = WeakUntil fp si (simplifyExpr a1) (simplifyExpr a2)
simplifyExpr (Or si a1 a2) = Or si (simplifyExpr a1) (simplifyExpr a2)
simplifyExpr (And si a1 a2) = And si (simplifyExpr a1) (simplifyExpr a2)
simplifyExpr (Equ si a1 a2) = Equ si (simplifyExpr a1) (simplifyExpr a2)
simplifyExpr (Impl si a1 a2) = Impl si (simplifyExpr a1) (simplifyExpr a2)
simplifyExpr (TPredict fp si r e) = TPredict fp si r (simplifyExpr e)
simplifyExpr (TUntil fp si r a1 a2) = TUntil fp si r (simplifyExpr a1) (simplifyExpr a2)
simplifyExpr (TWeakUntil fp si r a1 a2) = TWeakUntil fp si r (simplifyExpr a1) (simplifyExpr a2)
simplifyExpr (TAlways fp si r e) = TAlways fp si r (simplifyExpr e)
simplifyExpr (TEventually fp si r e) = TEventually fp si r (simplifyExpr e)
simplifyExpr (Error si s) = (Error si s)

