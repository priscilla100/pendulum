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

module SALT2RLTL (convertSALT2RLTL) where

import Maybe
import SALT
import RLTL
import SALTMacros
import Common
import Timed

-- This module defines the translation of core SALT into RLTL.

-- ***********************************************************
-- Helper functions
-- ***********************************************************

-- return an error expression that will be later collected and printed
returnError s e = RLTL.Error (SALT.getSI e) s

-- returns whether an expression contains only boolean operators
isPureBoolean :: SALT.Expr -> Bool
isPureBoolean (SALT.Ident _ i) = True
isPureBoolean (SALT.TT _)= True
isPureBoolean (SALT.FF _)= True
isPureBoolean (SALT.Or _ o1 o2) = (isPureBoolean o1) && (isPureBoolean o2)
isPureBoolean (SALT.And _ o1 o2) = (isPureBoolean o1) && (isPureBoolean o2)
isPureBoolean (SALT.Impl _ o1 o2) = (isPureBoolean o1) && (isPureBoolean o2)
isPureBoolean (SALT.Equ _ o1 o2) = (isPureBoolean o1) && (isPureBoolean o2)
isPureBoolean (SALT.Not _ n) = isPureBoolean n
isPureBoolean e = False

-- get the sequence length of the given expression
-- if there is no Int returned, it means there are temporal operators inside
-- or that there is & or | with arguments of different length
getSequenceLength :: FP -> SALT.Expr -> (Maybe Int)
getSequenceLength fp (SALT.Or _ o1 o2) = compareSequenceLength fp o1 o2
getSequenceLength fp (SALT.And _ o1 o2) = compareSequenceLength fp o1 o2
getSequenceLength fp (SALT.EmptySequence fp2 e) = 
  if (fp /= fp2) then Nothing
  else Just 0
getSequenceLength fp (SALT.RegExp fp2 _ e) = 
  if (fp /= fp2) then Nothing
  else (getSequenceLength fp e)
getSequenceLength fp (SALT.Sequence fp2 _ e1 e2) = 
  if (fp /= fp2) then Nothing
  else let l1 = getSequenceLength fp e1 in
    let l2 = getSequenceLength fp e2 in
      if ((isJust l1) && (isJust l2)) then Just ((fromJust l1) + (fromJust l2))
      else Nothing
getSequenceLength fp (SALT.OverlapSequence fp2 _ e1 e2) = 
  if (fp /= fp2) then Nothing
  else let l1 = getSequenceLength fp e1 in
    let l2 = getSequenceLength fp e2 in
      if ((isJust l1) && (isJust l2)) then Just ((fromJust l1) + (fromJust l2) - 1)
      else Nothing
getSequenceLength fp e = if (isPureBoolean e) then (Just 1) else Nothing

-- helper to make expressions that need a comparison shorter
compareSequenceLength :: FP -> SALT.Expr -> SALT.Expr -> (Maybe Int)
compareSequenceLength fp e1 e2 =
  let l1 = getSequenceLength fp e1 in
    let l2 = getSequenceLength fp e2 in
      if ((isJust l1) && (isJust l2)) then
        if ((fromJust l1) == (fromJust l2)) then l1 else Nothing
      else Nothing


-- ***********************************************************
-- The main conversion function
-- ***********************************************************
convertSALT2RLTL :: SALT.Expr -> RLTL.Expr

-- ***********************************************************
-- Expression with UpTo, From or Between

convertSALT2RLTL (SALT.UpTo fp si (SALT.Required _ e) (SALT.Exclusive _ (SALT.Required _ b))) =
  let rltlB = (convertSALT2RLTL b) in
    let rltlE = (convertSALT2RLTL e) in
      case rltlE of
      -- OPTIMIZED for always e => !b & (a stopon b) until b
      (RLTL.Always fp _ rltlEE) 
        -> (RLTL.And si (RLTL.Not si rltlB) (RLTL.Until fp si (RLTL.StopExcl fp si rltlEE rltlB) rltlB))
  	  -- OPTIMIZED for not eventually e => !b & (!a stopon b) until b
      (RLTL.Not _ (RLTL.Eventually fp _ rltlEE)) 
	    -> (RLTL.And si (RLTL.Not si rltlB) (RLTL.Until fp si (RLTL.StopExcl fp si (RLTL.Not si rltlEE) rltlB) rltlB))
      -- else:
      _ -> (RLTL.And si (RLTL.Eventually fp si rltlB) (RLTL.And si (RLTL.Not si rltlB) (RLTL.StopExcl fp si rltlE rltlB)))

convertSALT2RLTL (SALT.UpTo fp si (SALT.Required _ e) (SALT.Exclusive _ (SALT.Optional _ b))) =
  let rltlB = (convertSALT2RLTL b) in
    let rltlE = (convertSALT2RLTL e) in
      case rltlE of
      -- OPTIMIZED for eventually e => !((!e stopon b) until b)
      (RLTL.Eventually fp _ rltlEE) 
        -> (RLTL.Not si (RLTL.Until fp si (RLTL.Not si (RLTL.StopExcl fp si rltlEE rltlB)) rltlB))
      -- else:
      _ -> (RLTL.Impl si (RLTL.Eventually fp si rltlB) (RLTL.And si (RLTL.Not si rltlB) (RLTL.StopExcl fp si rltlE rltlB)))

convertSALT2RLTL (SALT.UpTo fp si (SALT.Required _ e) (SALT.Exclusive _ (SALT.Weak _ b))) = 
  let rltlB = (convertSALT2RLTL b) in
  (RLTL.And si (RLTL.Not si rltlB) (RLTL.StopExcl fp si (convertSALT2RLTL e) rltlB))

convertSALT2RLTL (SALT.UpTo fp si (SALT.Weak _ e) (SALT.Exclusive _ (SALT.Required _ b))) =
  let rltlB = (convertSALT2RLTL b) in
    let rltlE = (convertSALT2RLTL e) in
      case rltlE of
      -- OPTIMIZED for always e => (a stopon b) until b
      (RLTL.Always fp _ rltlEE)
        -> (RLTL.Until fp si (RLTL.StopExcl fp si rltlEE rltlB) rltlB)
      -- OPTIMIZED for not eventually e => (!a stopon b) until b
      (RLTL.Not _ (RLTL.Eventually fp _ rltlEE))
        -> (RLTL.Until fp si (RLTL.StopExcl fp si (RLTL.Not si rltlEE) rltlB) rltlB)
      -- else:
      _ ->(RLTL.And si (RLTL.Eventually fp si rltlB) (RLTL.Or si rltlB (RLTL.StopExcl fp si rltlE rltlB)))

convertSALT2RLTL (SALT.UpTo fp si (SALT.Weak _ e) (SALT.Exclusive _ (SALT.Optional _ b))) =
  let rltlB = (convertSALT2RLTL b) in
    let rltlE = (convertSALT2RLTL e) in
      case rltlE of
      -- OPTIMIZED for eventually e => b | !((!e stopon b) until b)
      (RLTL.Eventually fp _ rltlEE)
        -> (RLTL.Or si rltlB (RLTL.Not si (RLTL.Until fp si (RLTL.Not si (RLTL.StopExcl fp si rltlEE rltlB)) rltlB)))
      -- else:
      _ -> (RLTL.Impl si (RLTL.Eventually fp si rltlB) (RLTL.Or si rltlB (RLTL.StopExcl fp si rltlE rltlB)))

convertSALT2RLTL (SALT.UpTo fp si (SALT.Weak _ e) (SALT.Exclusive _ (SALT.Weak _ b))) = 
  let rltlB = (convertSALT2RLTL b) in
  (RLTL.Or si rltlB (RLTL.StopExcl fp si (convertSALT2RLTL e) rltlB))

convertSALT2RLTL (SALT.UpTo fp si e (SALT.Exclusive _ (SALT.Required _ b))) =
  let rltlB = (convertSALT2RLTL b) in
    let rltlE = (convertSALT2RLTL e) in
      case rltlE of
      -- OPTIMIZED for always e => (a stopon b) until b
      (RLTL.Always fp _ rltlEE)
        -> (RLTL.Until fp si (RLTL.StopExcl fp si rltlEE rltlB) rltlB)
      -- OPTIMIZED for not eventually e => (!a stopon b) until b
      (RLTL.Not _ (RLTL.Eventually fp _ rltlEE))
        -> (RLTL.Until fp si (RLTL.StopExcl fp si (RLTL.Not si rltlEE) rltlB) rltlB)
      -- else:
      _ -> (RLTL.And si (RLTL.Eventually fp si rltlB) (RLTL.StopExclCheck fp si rltlE rltlB))

convertSALT2RLTL (SALT.UpTo fp si e (SALT.Exclusive _ (SALT.Optional _ b))) =
  let rltlB = (convertSALT2RLTL b) in
    let rltlE = (convertSALT2RLTL e) in
      case rltlE of
      -- OPTIMIZED for eventually e => !((!e stopon b) until b)
      (RLTL.Eventually fp _ rltlEE)
        -> (RLTL.Not si (RLTL.Until fp si (RLTL.Not si (RLTL.StopExcl fp si rltlEE rltlB)) rltlB))
      -- else:
      _ -> (RLTL.Impl si (RLTL.Eventually fp si rltlB) (RLTL.StopExclCheck fp si rltlE rltlB))

convertSALT2RLTL (SALT.UpTo fp si e (SALT.Exclusive _ (SALT.Weak _ b))) = 
  (RLTL.StopExclCheck fp si (convertSALT2RLTL e) (convertSALT2RLTL b))

convertSALT2RLTL (SALT.UpTo fp si e (SALT.Inclusive _ (SALT.Required _ b))) =
  let rltlB = (convertSALT2RLTL b) in
    (RLTL.And si (RLTL.Eventually fp si rltlB) (RLTL.StopIncl fp si (convertSALT2RLTL e) rltlB))

convertSALT2RLTL (SALT.UpTo fp si e (SALT.Inclusive _ (SALT.Optional _ b))) =
  let rltlB = (convertSALT2RLTL b) in
    (RLTL.Impl si (RLTL.Eventually fp si rltlB) (RLTL.StopIncl fp si (convertSALT2RLTL e) rltlB))

convertSALT2RLTL (SALT.UpTo fp si e (SALT.Inclusive _ (SALT.Weak _ b))) = 
  let rltlB = (convertSALT2RLTL b) in
    let rltlE = (convertSALT2RLTL e) in
      case rltlE of
      -- OPTIMIZED for always e => !(!b until !e)
      (RLTL.Always fp _ rltlEE)
        -> (RLTL.Not si (RLTL.Until fp si (RLTL.Not si rltlB) (RLTL.Not si (RLTL.StopIncl fp si rltlEE rltlB))))
      -- OPTIMIZED for !eventually e => !(!b until e)
      (RLTL.Not _ (RLTL.Eventually fp _ rltlEE))
        -> (RLTL.Not si (RLTL.Until fp si (RLTL.Not si rltlB) (RLTL.StopIncl fp si rltlEE rltlB)))
      -- else
      _ -> (RLTL.StopIncl fp si rltlE rltlB)

convertSALT2RLTL (SALT.From fp si e (SALT.Inclusive _ (SALT.Required _ a))) = 
  (convertSALT2RLTL (SALT.Until fp si (SALT.Not si a) (SALT.And si a e)))

convertSALT2RLTL (SALT.From fp si e (SALT.Inclusive _ (SALT.Optional _ a))) = 
  let rltlA = (convertSALT2RLTL a) in
    let rltlE = (convertSALT2RLTL e) in
      case rltlE of
      -- OPTIMIZED for always e => always (a -> (always e))
      (RLTL.Always fp _ rltlEE)
        -> (RLTL.Always fp si (RLTL.Impl si rltlA (RLTL.Always fp si rltlEE)))
      -- OPTIMIZED for not eventually e => always (a -> (not eventually e))
      (RLTL.Not _ (RLTL.Eventually fp _ rltlEE))
        -> (RLTL.Always fp si (RLTL.Impl si rltlA (RLTL.Not si (RLTL.Eventually fp si rltlEE))))
      -- else
      _ -> (RLTL.WeakUntil fp si (RLTL.Not si rltlA) (RLTL.And si rltlA rltlE))

convertSALT2RLTL (SALT.From fp si e (SALT.Exclusive _ (SALT.Required _ a))) = 
  (convertSALT2RLTL (SALT.Until fp si (SALT.Not si a) (SALT.And si a (SALT.Next fp si e))))

convertSALT2RLTL (SALT.From fp si e (SALT.Exclusive _ (SALT.Optional _ a))) = 
  (convertSALT2RLTL (SALT.Until fp si (SALT.Not si a) (SALT.Weak si (SALT.And si a (SALT.Next fp si e)))))

convertSALT2RLTL (SALT.Between fp si e a b) =
  (convertSALT2RLTL (SALT.From fp si (SALT.UpTo fp si e b) a))




-- ***********************************************************
-- Timed Expressions, must be matched before untimed exprs. 

-- standard operators
convertSALT2RLTL (SALT.Next fp si (SALT.Timed si2 r e)) =
  RLTL.TPredict fp si r (convertSALT2RLTL e)
convertSALT2RLTL (SALT.Eventually fp si (SALT.Timed si2 r e)) =
  RLTL.TEventually fp si r (convertSALT2RLTL e)
convertSALT2RLTL (SALT.Always fp si (SALT.Timed si2 r e)) =
  RLTL.TAlways fp si r (convertSALT2RLTL e)

-- until in 6 variants
convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed _ r (SALT.Exclusive _ (SALT.Required _ u2)))) =
    (RLTL.TUntil fp si r (convertSALT2RLTL u1) (convertSALT2RLTL u2)) 
convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed _ r (SALT.Exclusive _ (SALT.Optional _ u2)))) =
  let rltlU2 = (convertSALT2RLTL u2) in
    (RLTL.Impl si (RLTL.TEventually fp si r rltlU2) (RLTL.TUntil fp si r (convertSALT2RLTL u1) rltlU2)) 
convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed _ r (SALT.Exclusive _ (SALT.Weak _ u2)))) =
    (RLTL.TWeakUntil fp si r (convertSALT2RLTL u1) (convertSALT2RLTL u2)) 
convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed _ r (SALT.Inclusive _ (SALT.Required _ u2)))) =
  let rltlU1 = (convertSALT2RLTL u1) in
    (RLTL.TUntil fp si r rltlU1 (RLTL.And si rltlU1 (convertSALT2RLTL u2))) 
convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed _ r (SALT.Inclusive _ (SALT.Optional _ u2)))) =
  let rltlU1 = (convertSALT2RLTL u1) in
  let rltlU2 = (convertSALT2RLTL u2) in
    (RLTL.Impl si (RLTL.TEventually fp si r rltlU2) (RLTL.TUntil fp si r rltlU1 (RLTL.And si rltlU1 rltlU2)) ) 
convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed _ r (SALT.Inclusive _ (SALT.Weak _ u2)))) =
  let rltlU1 = (convertSALT2RLTL u1) in
    RLTL.TWeakUntil fp si r rltlU1 (RLTL.And si rltlU1 (convertSALT2RLTL u2))
    
-- until - shortcuts for default variants    
convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed si2 r (SALT.Weak si3 u2))) =
  convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed si2 r (SALT.Exclusive si (SALT.Weak si3 u2)))) 
convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed si2 r u2)) =
  convertSALT2RLTL (SALT.Until fp si u1 (SALT.Timed si2 r (SALT.Exclusive si (SALT.Required si u2)))) 

-- ***********************************************************
-- Expression with Standard temporal operators

convertSALT2RLTL (SALT.Eventually fp si a) = RLTL.Eventually fp si (convertSALT2RLTL a)
convertSALT2RLTL (SALT.Always fp si a) = RLTL.Always fp si (convertSALT2RLTL a)
convertSALT2RLTL (SALT.Next fp si (SALT.Weak _ a)) = RLTL.Not si (RLTL.Next fp si (RLTL.Not si (convertSALT2RLTL a)))
convertSALT2RLTL (SALT.Next fp si a) = RLTL.Next fp si (convertSALT2RLTL a)
convertSALT2RLTL (SALT.Until fp si a1 (SALT.Exclusive _ (SALT.Required _ a2))) = 
    RLTL.Until fp si (convertSALT2RLTL a1) (convertSALT2RLTL a2)
convertSALT2RLTL (SALT.Until fp si a1 (SALT.Exclusive _ (SALT.Optional _ a2))) = 
    let rltlA2 = (convertSALT2RLTL a2) in
    RLTL.Impl si (RLTL.Eventually fp si rltlA2) (RLTL.Until fp si (convertSALT2RLTL a1) (rltlA2))
convertSALT2RLTL (SALT.Until fp si a1 (SALT.Exclusive _ (SALT.Weak _ a2))) = 
    RLTL.WeakUntil fp si (convertSALT2RLTL a1) (convertSALT2RLTL a2)
convertSALT2RLTL (SALT.Until fp si a1 (SALT.Inclusive _ (SALT.Required _ a2))) = 
    let rltlA1 = (convertSALT2RLTL a1) in
    RLTL.Until fp si rltlA1 (RLTL.And si rltlA1 (convertSALT2RLTL a2))
convertSALT2RLTL (SALT.Until fp si a1 (SALT.Inclusive _ (SALT.Optional _ a2))) = 
    let rltlA1 = (convertSALT2RLTL a1) in
    let rltlA2 = (convertSALT2RLTL a2) in
    RLTL.Impl si (RLTL.Eventually fp si rltlA2) (RLTL.Until fp si rltlA1 (RLTL.And si rltlA1 rltlA2))
convertSALT2RLTL (SALT.Until fp si a1 (SALT.Inclusive _ (SALT.Weak _ a2))) = 
    let rltlA1 = (convertSALT2RLTL a1) in
    RLTL.WeakUntil fp si rltlA1 (RLTL.And si rltlA1 (convertSALT2RLTL a2))

convertSALT2RLTL (SALT.Until fp si a1 (SALT.Weak _ a2)) = 
    RLTL.WeakUntil fp si (convertSALT2RLTL a1) (convertSALT2RLTL a2)
convertSALT2RLTL (SALT.Until fp si a1 a2) = 
    RLTL.Until fp si (convertSALT2RLTL a1) (convertSALT2RLTL a2)


-- ***********************************************************
-- Expression with Standard boolean operators

convertSALT2RLTL (SALT.TT si)= RLTL.TT si
convertSALT2RLTL (SALT.FF si)= RLTL.FF si
convertSALT2RLTL (SALT.Ident si i) = RLTL.Ident si i
convertSALT2RLTL (SALT.Not si a) = RLTL.Not si (convertSALT2RLTL a)
convertSALT2RLTL (SALT.And si a1 a2) = RLTL.And si (convertSALT2RLTL a1) (convertSALT2RLTL a2)
convertSALT2RLTL (SALT.Or si a1 a2) = RLTL.Or si (convertSALT2RLTL a1) (convertSALT2RLTL a2)
convertSALT2RLTL (SALT.Impl si a1 a2) = RLTL.Impl si (convertSALT2RLTL a1) (convertSALT2RLTL a2)
convertSALT2RLTL (SALT.Equ si a1 a2) = RLTL.Equ si (convertSALT2RLTL a1) (convertSALT2RLTL a2)


-- ***********************************************************
-- Expression with Accept/Reject

convertSALT2RLTL (SALT.Accept si e b) = RLTL.Accept si (convertSALT2RLTL e) (convertSALT2RLTL b)
convertSALT2RLTL (SALT.Reject si e b) = RLTL.Reject si (convertSALT2RLTL e) (convertSALT2RLTL b)


-- ***********************************************************
-- Expression with Sequences and repetitions that have not been
-- translated in SALTMacros

-- remove trailing empty sequence, because it would result in an
-- extra "next true", which is semantically different
convertSALT2RLTL (SALT.Sequence fp si a (SALT.EmptySequence fp2 si2)) = 
  convertSALT2RLTL a
convertSALT2RLTL (SALT.OverlapSequence fp si a (SALT.EmptySequence fp2 si2)) = 
  convertSALT2RLTL a
-- in other cases, the empty sequence can be assumed to be true
convertSALT2RLTL (SALT.EmptySequence fp si) = RLTL.TT si

-- RegExp serves mainly as marker so that expressions like
-- /!/a/;b/ are NOT allowed, but /!a;b/ is
convertSALT2RLTL (SALT.RegExp fp si e) =
  convertSALT2RLTL e

-- The following expressions help to sort sequences,
-- so that e.g. / /a;b/; c/ becomes /a; /b;c/ /
convertSALT2RLTL (SALT.Sequence fp si (SALT.RegExp fp2 si2 a) b) =
  if (fp /= fp2) then RLTL.Error si2 "Mixed future and past regular expression"
  else convertSALT2RLTL (SALT.Sequence fp si a b)
convertSALT2RLTL (SALT.OverlapSequence fp si (SALT.RegExp fp2 si2 a) b) =
  if (fp /= fp2) then RLTL.Error si2 "Mixed future and past regular expression"
  else convertSALT2RLTL (SALT.OverlapSequence fp si a b)
convertSALT2RLTL (SALT.Sequence fp si (SALT.Sequence fp2 si2 a b) c) =
  if (fp /= fp2) then RLTL.Error si2 "Mixed future and past regular expression"
  else convertSALT2RLTL (SALT.Sequence fp si a (SALT.Sequence fp si2 b c))
convertSALT2RLTL (SALT.OverlapSequence fp si (SALT.Sequence fp2 si2 a b) c) =
  if (fp /= fp2) then RLTL.Error si2 "Mixed future and past regular expression"
  else convertSALT2RLTL (SALT.Sequence fp si a (SALT.OverlapSequence fp si2 b c))
convertSALT2RLTL (SALT.Sequence fp si (SALT.OverlapSequence fp2 si2 a b) c) =
  if (fp /= fp2) then RLTL.Error si2 "Mixed future and past regular expression"
  else convertSALT2RLTL (SALT.OverlapSequence fp si a (SALT.Sequence fp si2 b c))
convertSALT2RLTL (SALT.OverlapSequence fp si (SALT.OverlapSequence fp2 si2 a b) c) =
  if (fp /= fp2) then RLTL.Error si2 "Mixed future and past regular expression"
  else convertSALT2RLTL (SALT.OverlapSequence fp si a (SALT.OverlapSequence fp si2 b c))

-- a*[>=0]; b => a until b
-- a*[>=n]; b => a until (a*[=n]; b)
convertSALT2RLTL (SALT.Sequence fp si (SALT.RepeatGreaterOrEqual fp2 si2 n a) b) =
  if (fp /= fp2) then RLTL.Error si2 "Mixed future and past regular expression"
  else if (not (isPureBoolean a)) then returnError "Pure boolean expression expected" a
    else if (n == 0) then (RLTL.Until fp si (convertSALT2RLTL a) (convertSALT2RLTL b))
      else (RLTL.Until fp si (convertSALT2RLTL a) 
           (convertSALT2RLTL (SALT.Sequence fp si (SALTMacros.repeat fp si2 (SALTMacros.Exactly si2 n) a) b)))

-- (a1 | a2); b => a1; b | a2; b         
-- a; b => a & (nextn[|a|] b)
convertSALT2RLTL (SALT.Sequence fp si a b) = 
  let l1 = (getSequenceLength fp a) in
    if (isNothing l1) then case a of
      (SALT.Or si2 xa ya)
        -> convertSALT2RLTL (SALT.Or si2 (SALT.Sequence fp si xa b)
                                (SALT.Sequence fp si ya b))
      _ -> returnError "Invalid expression within sequence" a
    else RLTL.And si (convertSALT2RLTL a) (convertSALT2RLTL (nextn fp si (SALTMacros.Exactly si (fromJust l1)) b))
  
-- a*[>=0]: b => b | (a*[>=1]: b)
-- a*[>=n]: b => a until (a*[=n]: b)
convertSALT2RLTL (SALT.OverlapSequence fp si (SALT.RepeatGreaterOrEqual fp2 si2 n a) b) =
  if (fp /= fp2) then RLTL.Error si2 "Mixed future and past regular expression"
  else if (not (isPureBoolean a)) then returnError "Pure boolean expression expected" a
    else if (n == 0) then (RLTL.Or si2 (convertSALT2RLTL b) 
                          (convertSALT2RLTL (SALT.OverlapSequence fp si (SALT.RepeatGreaterOrEqual fp si2 1 a) b)))
      else (RLTL.Until fp si2 (convertSALT2RLTL a) (
        convertSALT2RLTL (SALT.OverlapSequence fp si (SALTMacros.repeat fp si2 (SALTMacros.Exactly si2 n) a) b)))
  
-- (a1 | a2): b => a1: b | a2; b         
-- a: b => a & (nextn[|a|-1] b)
convertSALT2RLTL (SALT.OverlapSequence fp si a b) = 
  let l1 = (getSequenceLength fp a) in
    if (isNothing l1) then case a of
      (SALT.Or si2 xa ya)
        -> convertSALT2RLTL (SALT.Or si2 (SALT.OverlapSequence fp si xa b)
                                (SALT.OverlapSequence fp si ya b))
      _ -> returnError "Invalid expression within sequence" a
    else if (fromJust l1) == 0 then (convertSALT2RLTL b)
    else RLTL.And si (convertSALT2RLTL a) (convertSALT2RLTL (nextn fp si (SALTMacros.Exactly si ((fromJust l1) - 1)) b))

-- a*[>=n] at end of sequence => a*[=n]
convertSALT2RLTL (SALT.RepeatGreaterOrEqual fp si n a) = 
  convertSALT2RLTL (SALTMacros.repeat fp si (SALTMacros.Exactly si n) a) 



-- ***********************************************************
-- Malformed expressions

convertSALT2RLTL (SALT.Required si a) = RLTL.Error si "required used in an inappropriate place" 
convertSALT2RLTL (SALT.Optional si a) = RLTL.Error si "optional used in an inappropriate place" 
convertSALT2RLTL (SALT.Weak si a) = RLTL.Error si "weak used in an inappropriate place" 
convertSALT2RLTL (SALT.Inclusive si a) = RLTL.Error si "inclusive used in an inappropriate place" 
convertSALT2RLTL (SALT.UpTo _ _ e b) = returnError "Operator must be used with inclusive/exclusive and required, optional or weak" b
convertSALT2RLTL (SALT.From _ _ e a) = returnError "Operator must be used with inclusive/exclusive and required or optional" a
convertSALT2RLTL (SALT.Timed si r a) = RLTL.Error si "timed used in an inappropriate place" 
    
convertSALT2RLTL (SALT.Error si s) = (RLTL.Error si s)
convertSALT2RLTL e = returnError "Internal error: no translation found for expression" e  
    