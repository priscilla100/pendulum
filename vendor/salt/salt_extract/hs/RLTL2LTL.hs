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

module RLTL2LTL (convertRLTL2LTL) where

import LTL
import RLTL
import Common
import OptimizeLTL

-- This module defines the translation of RLTL into LTL, i.e.
-- the weaving of reject-, accept- and stop-conditions into 
-- the formula.

-- *********************************************************************
-- Helper functions
-- *********************************************************************

-- is the given expression a pure boolean proposition?
isBoolProp :: LTL.Expr -> Bool
isBoolProp (LTL.Ident _ i) = True
isBoolProp (LTL.TT _)= True
isBoolProp (LTL.FF _)= True
isBoolProp (LTL.Or _ o1 o2) = (isBoolProp o1) && (isBoolProp o2)
isBoolProp (LTL.And _ a1 a2) = (isBoolProp a1) && (isBoolProp a2)
isBoolProp (LTL.Impl _ a1 a2) = (isBoolProp a1) && (isBoolProp a2)
isBoolProp (LTL.Equ _ a1 a2) = (isBoolProp a1) && (isBoolProp a2)
isBoolProp (LTL.Not _ n) = isBoolProp n
isBoolProp (LTL.Error _ e) = True
isBoolProp e = False

-- converts a pure boolean proposition from RLTL to LTL
convertPureBoolRLTL2LTL :: RLTL.Expr -> LTL.Expr 
convertPureBoolRLTL2LTL (RLTL.Not si n) = LTL.Not si (convertPureBoolRLTL2LTL n)
convertPureBoolRLTL2LTL (RLTL.Or si o1 o2) = LTL.Or si (convertPureBoolRLTL2LTL o1) (convertPureBoolRLTL2LTL o2) 
convertPureBoolRLTL2LTL (RLTL.And si a1 a2) = LTL.And si (convertPureBoolRLTL2LTL a1) (convertPureBoolRLTL2LTL a2) 
convertPureBoolRLTL2LTL (RLTL.Equ si a1 a2) = LTL.Equ si (convertPureBoolRLTL2LTL a1) (convertPureBoolRLTL2LTL a2) 
convertPureBoolRLTL2LTL (RLTL.Impl si a1 a2) = LTL.Impl si (convertPureBoolRLTL2LTL a1) (convertPureBoolRLTL2LTL a2) 
convertPureBoolRLTL2LTL (RLTL.TT si)= (LTL.TT si)
convertPureBoolRLTL2LTL (RLTL.FF si)= (LTL.FF si)
convertPureBoolRLTL2LTL (RLTL.Ident si i) = LTL.Ident si i
convertPureBoolRLTL2LTL (RLTL.Error si e) = LTL.Error si e
convertPureBoolRLTL2LTL e = LTL.Error (getLeftSI e) "Pure boolean expression expected" 

-- Adds stop conditions to a formula
-- parameters: expr cond fp
addNegStopCondition :: LTL.Expr -> LTL.Expr -> LTL.Expr
addNegStopCondition e s = (LTL.And (LTL.getSI e) e (LTL.Not (LTL.getSI e) s))

addPosStopCondition :: LTL.Expr -> LTL.Expr -> LTL.Expr
addPosStopCondition e s = (LTL.Or (LTL.getSI e) e s)

-- tests whether a formula is a valid argument for StopExcl,
-- i.e. whether it is an until, eventually, always, not
isValidStopExclArg :: FP -> RLTL.Expr -> Bool
isValidStopExclArg fp (RLTL.Until fp2 _ e1 e2) = fp == fp2
isValidStopExclArg fp (RLTL.WeakUntil fp2 _ e1 e2) = fp == fp2
isValidStopExclArg fp (RLTL.Always fp2 _ e) = fp == fp2
isValidStopExclArg fp (RLTL.Eventually fp2 _ e) = fp == fp2
isValidStopExclArg fp (RLTL.Not _ e) = isValidStopExclArg fp e
isValidStopExclArg fp (RLTL.And _ e1 e2) = (isValidStopExclArg fp e1) && (isValidStopExclArg fp e2)
isValidStopExclArg fp (RLTL.Or _ e1 e2) = (isValidStopExclArg fp e1) && (isValidStopExclArg fp e2)
isValidStopExclArg fp (RLTL.Equ _ e1 e2) = (isValidStopExclArg fp e1) && (isValidStopExclArg fp e2)
isValidStopExclArg fp (RLTL.Impl _ e1 e2) = (isValidStopExclArg fp e1) && (isValidStopExclArg fp e2)
isValidStopExclArg fp (RLTL.Error _ e) = True
isValidStopExclArg fp e = False

-- *********************************************************************

-- converts an LTL expr that is not pure boolean replacing StopExcl
-- parameters: expr stop stopinpast
weaveStopExcl	:: LTL.Expr -> LTL.Expr -> FP -> LTL.Expr
weaveStopExcl (LTL.Not si n) s fp = LTL.Not si (weaveStopExcl n s fp)
weaveStopExcl (LTL.Or si o1 o2) s fp = LTL.Or si (weaveStopExcl o1 s fp) (weaveStopExcl o2 s fp) 
weaveStopExcl (LTL.And si a1 a2) s fp = LTL.And si (weaveStopExcl a1 s fp) (weaveStopExcl a2 s fp) 
weaveStopExcl (LTL.Equ si a1 a2) s fp = LTL.Equ si (weaveStopExcl a1 s fp) (weaveStopExcl a2 s fp) 
weaveStopExcl (LTL.Impl si a1 a2) s fp = LTL.Impl si (weaveStopExcl a1 s fp) (weaveStopExcl a2 s fp) 
weaveStopExcl (LTL.TT si) s fp = (LTL.TT si)
weaveStopExcl (LTL.FF si) s fp = (LTL.FF si)
weaveStopExcl (LTL.Ident si i) s fp = (LTL.Ident si i)

weaveStopExcl (LTL.Until fp2 si u1 u2) s fp = 
  if (fp == fp2) then
  LTL.Until fp si (addNegStopCondition (weaveStopExcl u1 s fp) s) (addNegStopCondition (weaveStopExcl u2 s fp) s)
  else 
  LTL.Until fp2 si (weaveStopExcl u1 s fp) (weaveStopExcl u2 s fp) 
weaveStopExcl (LTL.WeakUntil fp2 si u1 u2) s fp = 
  if (fp == fp2) then
  LTL.WeakUntil fp si (weaveStopExcl u1 s fp) (addPosStopCondition (weaveStopExcl u2 s fp) s)
  else
  LTL.WeakUntil fp2 si (weaveStopExcl u1 s fp) (weaveStopExcl u2 s fp) 
weaveStopExcl (LTL.Next fp2 si n) s fp = 
  if (fp == fp2) then
  (LTL.Next fp si (addNegStopCondition (weaveStopExcl n s fp) s))
  else
  (LTL.Next fp2 si (weaveStopExcl n s fp))
weaveStopExcl (LTL.Always fp2 si n) s fp = 
  if (fp == fp2) then
  LTL.WeakUntil fp si (weaveStopExcl n s fp) (addPosStopCondition (LTL.FF si) s)
  else
  LTL.Always fp2 si (weaveStopExcl n s fp)
weaveStopExcl (LTL.Eventually fp2 si n) s fp = 
  if (fp == fp2) then
  (weaveStopExcl (replaceEventually fp si n) s fp)
  else 
  LTL.Eventually fp2 si (weaveStopExcl n s fp)

weaveStopExcl (LTL.TPredict fp2 si r e) s fp =   
  LTL.TPredict fp2 si r e
weaveStopExcl (LTL.TAlways fp2 si r e) s fp =   
  LTL.TAlways fp2 si r e
weaveStopExcl (LTL.TEventually fp2 si r e) s fp =   
  LTL.TEventually fp2 si r e
weaveStopExcl (LTL.TUntil fp2 si r u1 u2) s fp =    
  LTL.TUntil fp2 si r u1 u2 
weaveStopExcl (LTL.TWeakUntil fp2 si r u1 u2) s fp =    
  LTL.TWeakUntil fp2 si r u1 u2 
    
weaveStopExcl (LTL.Error si e) s fp = LTL.Error si e

-- *********************************************************************

-- converts an LTL expr that is not pure boolean replacing StopIncl
-- parameters: expr stop stopinpast
weaveStopIncl	:: LTL.Expr -> LTL.Expr -> FP -> LTL.Expr
weaveStopIncl (LTL.Not si n) s fp = LTL.Not si (weaveStopIncl n s fp)
weaveStopIncl (LTL.Or si o1 o2) s fp = LTL.Or si (weaveStopIncl o1 s fp) (weaveStopIncl o2 s fp) 
weaveStopIncl (LTL.And si a1 a2) s fp = LTL.And si (weaveStopIncl a1 s fp) (weaveStopIncl a2 s fp) 
weaveStopIncl (LTL.Equ si a1 a2) s fp = LTL.Equ si (weaveStopIncl a1 s fp) (weaveStopIncl a2 s fp) 
weaveStopIncl (LTL.Impl si a1 a2) s fp = LTL.Impl si (weaveStopIncl a1 s fp) (weaveStopIncl a2 s fp) 
weaveStopIncl (LTL.TT si) s fp = (LTL.TT si)
weaveStopIncl (LTL.FF si) s fp = (LTL.FF si)
weaveStopIncl (LTL.Ident si i) s fp = (LTL.Ident si i)

weaveStopIncl (LTL.Until fp2 si u1 u2) s fp = 
  if (fp == fp2) then
  LTL.Until fp si (addNegStopCondition (weaveStopIncl u1 s fp) s) (weaveStopIncl u2 s fp) 
  else
  LTL.Until fp2 si (weaveStopIncl u1 s fp) (weaveStopIncl u2 s fp) 
weaveStopIncl (LTL.WeakUntil fp2 si u1 u2) s fp = 
  if (fp == fp2) then
  (weaveStopIncl (replaceWeakUntilByBest fp si u1 u2) s fp)
  else
  LTL.WeakUntil fp2 si (weaveStopIncl u1 s fp) (weaveStopIncl u2 s fp) 
weaveStopIncl (LTL.Next fp2 si n) s fp = 
  if (fp == fp2) then
  (addNegStopCondition (LTL.Next fp si (weaveStopIncl n s fp)) s)
  else
  LTL.Next fp2 si (weaveStopIncl n s fp)
weaveStopIncl (LTL.Always fp2 si n) s fp = 
  if (fp == fp2) then
  (weaveStopIncl (replaceAlways fp si n) s fp)
  else
  LTL.Always fp2 si (weaveStopIncl n s fp)
weaveStopIncl (LTL.Eventually fp2 si n) s fp = 
  if (fp == fp2) then
  (weaveStopIncl (replaceEventually fp si n) s fp)
  else
  LTL.Eventually fp2 si (weaveStopIncl n s fp)

weaveStopIncl (LTL.TPredict fp2 si r e) s fp =   
  LTL.TPredict fp2 si r e
weaveStopIncl (LTL.TAlways fp2 si r e) s fp =   
  LTL.TAlways fp2 si r e
weaveStopIncl (LTL.TEventually fp2 si r e) s fp =   
  LTL.TEventually fp2 si r e
weaveStopIncl (LTL.TUntil fp2 si r u1 u2) s fp =    
  LTL.TUntil fp2 si r u1 u2 
weaveStopIncl (LTL.TWeakUntil fp2 si r u1 u2) s fp =    
  LTL.TWeakUntil fp2 si r u1 u2 
    
weaveStopIncl (LTL.Error si e) s fp = LTL.Error si e

-- *********************************************************************

-- converts an expr adding accept/reject condition, testing for pure boolean branches
weaveReject_TestPure :: LTL.Expr -> LTL.Expr -> LTL.Expr
weaveReject_TestPure e r = if (isBoolProp e) then addNegStopCondition e r
							       else (weaveReject_Helper e r)

-- converts an expr that is not pure boolean adding accept/reject condition
weaveReject_Helper	:: LTL.Expr -> LTL.Expr -> LTL.Expr
weaveReject_Helper (LTL.Not si n) r = LTL.Not si (weaveAccept_TestPure n r)
weaveReject_Helper (LTL.Or si o1 o2) r = LTL.Or si (weaveReject_TestPure o1 r) (weaveReject_TestPure o2 r) 
weaveReject_Helper (LTL.And si a1 a2) r = LTL.And si (weaveReject_TestPure a1 r) (weaveReject_TestPure a2 r) 
weaveReject_Helper (LTL.Equ si a1 a2) r = 
  weaveReject_Helper (LTL.Or si (LTL.And si (LTL.Not si a1) (LTL.Not si a2)) (LTL.And si a1 a2)) r 
weaveReject_Helper (LTL.Impl si a1 a2) r = LTL.Impl si (weaveAccept_TestPure a1 r) (weaveReject_TestPure a2 r) 

weaveReject_Helper (LTL.Until fp si u1 u2) r = 
  LTL.Until fp si (weaveReject_TestPure u1 r) (weaveReject_TestPure u2 r) 
weaveReject_Helper (LTL.WeakUntil fp si u1 u2) r = 
  (weaveReject_Helper (replaceWeakUntilByBest fp si u1 u2) r)
weaveReject_Helper (LTL.Next fp si n) r = 
  addNegStopCondition (LTL.Next fp si (weaveReject_TestPure n r)) r
weaveReject_Helper (LTL.Always fp si n) r = 
  LTL.Always fp si (weaveReject_TestPure n r)
weaveReject_Helper (LTL.Eventually fp si n) r = 
  (weaveReject_Helper (replaceEventually fp si n) r)

weaveReject_Helper (LTL.TPredict fp si range e) r = 
    (LTL.And si 
      (LTL.And si
        (LTL.Not si r)
        (LTL.Next fp si (LTL.Until fp si (LTL.Not si r) (weaveReject_TestPure e r)))
      )
      (LTL.TPredict fp si range (weaveReject_TestPure e r))
    )
weaveReject_Helper (LTL.TAlways fp si range e) r =    
  LTL.TAlways fp si range (weaveReject_TestPure e r)
weaveReject_Helper (LTL.TEventually fp si range e) r =    
  LTL.TUntil fp si range (LTL.Not si r) (weaveReject_TestPure e r)
weaveReject_Helper (LTL.TUntil fp si range u1 u2) r =    
  LTL.TUntil fp si range (weaveReject_TestPure u1 r) (weaveReject_TestPure u2 r) 
weaveReject_Helper (LTL.TWeakUntil fp si range u1 u2) r =    
  (weaveReject_Helper (replaceTWeakUntilByBest fp si range u1 u2) r)
    
weaveReject_Helper (LTL.Error si s) r = LTL.Error si s

-- *********************************************************************

-- converts an expr adding accept/reject condition, testing for pure boolean branches
weaveAccept_TestPure :: LTL.Expr -> LTL.Expr -> LTL.Expr
weaveAccept_TestPure e a = if (isBoolProp e) then addPosStopCondition e a
							       else (weaveAccept_Helper e a)

-- converts an expr that is not pure boolean adding accept/reject condition
weaveAccept_Helper	:: LTL.Expr -> LTL.Expr -> LTL.Expr
weaveAccept_Helper (LTL.Not si n) a = LTL.Not si (weaveReject_TestPure n a)
weaveAccept_Helper (LTL.Or si o1 o2) a = LTL.Or si (weaveAccept_TestPure o1 a) (weaveAccept_TestPure o2 a) 
weaveAccept_Helper (LTL.And si a1 a2) a = LTL.And si (weaveAccept_TestPure a1 a) (weaveAccept_TestPure a2 a) 
weaveAccept_Helper (LTL.Equ si a1 a2) a = 
  weaveAccept_Helper (LTL.Or si (LTL.And si (LTL.Not si a1) (LTL.Not si a2)) (LTL.And si a1 a2)) a 
weaveAccept_Helper (LTL.Impl si a1 a2) a = LTL.Impl si (weaveReject_TestPure a1 a) (weaveAccept_TestPure a2 a) 

weaveAccept_Helper (LTL.Until fp si u1 u2) a = 
  LTL.Until fp si (weaveAccept_TestPure u1 a) (weaveAccept_TestPure u2 a) 
weaveAccept_Helper (LTL.WeakUntil fp si u1 u2) a = 
  (weaveAccept_Helper (replaceWeakUntilByBest fp si u1 u2) a)
weaveAccept_Helper (LTL.Next fp si n) a = 
  addPosStopCondition (LTL.Next fp si (weaveAccept_TestPure n a)) a
weaveAccept_Helper (LTL.Always fp si n) a = 
  (weaveAccept_Helper (replaceAlways fp si n) a)
weaveAccept_Helper (LTL.Eventually fp si n) a = 
  LTL.Eventually fp si (weaveAccept_TestPure n a) 

weaveAccept_Helper (LTL.TPredict fp si range e) a  = 
  LTL.Or si
    a
    (LTL.TPredict fp si range (weaveAccept_TestPure e a))
weaveAccept_Helper (LTL.TAlways fp si range e) a =    
  LTL.Not si (LTL.TUntil fp si range (LTL.Not si a) (weaveReject_TestPure (LTL.Not si e) a))
weaveAccept_Helper (LTL.TEventually fp si range e) a =    
  LTL.TEventually fp si range (weaveAccept_TestPure e a)
weaveAccept_Helper (LTL.TUntil fp si range u1 u2) a =    
  LTL.TUntil fp si range (weaveAccept_TestPure u1 a) (weaveAccept_TestPure u2 a) 
weaveAccept_Helper (LTL.TWeakUntil fp si range u1 u2) a =    
  (weaveAccept_Helper (replaceTWeakUntilByBest fp si range u1 u2) a)
    
weaveAccept_Helper (LTL.Error si s) a = LTL.Error si s

-- *********************************************************************

-- the function to use externally
convertRLTL2LTL :: RLTL.Expr -> LTL.Expr 

convertRLTL2LTL (RLTL.Not si n) = LTL.Not si (convertRLTL2LTL n)
convertRLTL2LTL (RLTL.Or si o1 o2) = LTL.Or si (convertRLTL2LTL o1) (convertRLTL2LTL o2) 
convertRLTL2LTL (RLTL.And si a1 a2) = LTL.And si (convertRLTL2LTL a1) (convertRLTL2LTL a2) 
convertRLTL2LTL (RLTL.Equ si a1 a2) = LTL.Equ si (convertRLTL2LTL a1) (convertRLTL2LTL a2) 
convertRLTL2LTL (RLTL.Impl si a1 a2) = LTL.Impl si (convertRLTL2LTL a1) (convertRLTL2LTL a2) 
convertRLTL2LTL (RLTL.TT si) = (LTL.TT si)
convertRLTL2LTL (RLTL.FF si) = (LTL.FF si)
convertRLTL2LTL (RLTL.Ident si i) = (LTL.Ident si i)
convertRLTL2LTL (RLTL.Error si e) = (LTL.Error si e)
convertRLTL2LTL (RLTL.TPredict fp si r e) = (LTL.TPredict fp si r (convertRLTL2LTL e))
convertRLTL2LTL (RLTL.TUntil fp si r e1 e2) = (LTL.TUntil fp si r (convertRLTL2LTL e1) (convertRLTL2LTL e2))
convertRLTL2LTL (RLTL.TAlways fp si r e) = (LTL.TAlways fp si r (convertRLTL2LTL e))
convertRLTL2LTL (RLTL.TEventually fp si r e) = (LTL.TEventually fp si r (convertRLTL2LTL e))
convertRLTL2LTL (RLTL.TWeakUntil fp si r e1 e2) = (LTL.TWeakUntil fp si r (convertRLTL2LTL e1) (convertRLTL2LTL e2))

convertRLTL2LTL (RLTL.Until fp si a1 a2) = LTL.Until fp si (convertRLTL2LTL a1) (convertRLTL2LTL a2) 
convertRLTL2LTL (RLTL.WeakUntil fp si a1 a2) = LTL.WeakUntil fp si (convertRLTL2LTL a1) (convertRLTL2LTL a2) 
convertRLTL2LTL (RLTL.Always fp si n) = LTL.Always fp si (convertRLTL2LTL n)
convertRLTL2LTL (RLTL.Eventually fp si n) = LTL.Eventually fp si (convertRLTL2LTL n)
convertRLTL2LTL (RLTL.Next fp si n) = LTL.Next fp si (convertRLTL2LTL n)

convertRLTL2LTL (RLTL.StopExclCheck fp si e b) = 
  if (isValidStopExclArg fp e) then (weaveStopExcl (convertRLTL2LTL e) (convertPureBoolRLTL2LTL b) fp) 
  else LTL.Error (getLeftSI e) "Explicit required or weak needed" 
convertRLTL2LTL (RLTL.StopExcl fp si e b) = 
  (weaveStopExcl (convertRLTL2LTL e) (convertPureBoolRLTL2LTL b) fp)
convertRLTL2LTL (RLTL.StopIncl fp si e b) = 
  (weaveStopIncl (convertRLTL2LTL e) (convertPureBoolRLTL2LTL b) fp) 
convertRLTL2LTL (RLTL.Accept si e b) = 
  weaveAccept_TestPure (convertRLTL2LTL e) (convertPureBoolRLTL2LTL b) 
convertRLTL2LTL (RLTL.Reject si e b) = 
  weaveReject_TestPure (convertRLTL2LTL e) (convertPureBoolRLTL2LTL b)
