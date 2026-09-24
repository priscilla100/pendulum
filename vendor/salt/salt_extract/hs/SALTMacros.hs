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

module SALTMacros (enumerate, inexpressions,  
  with, without, 
  allof, someof, noneof, exactlyoneof, 
  never, nextn, holding, occurring, releases, SALTMacros.repeat,
  required, optional, weak,
  inclusive, exclusive, timed,
  Range(..)) where

-- This module defines the functions that are used to translate
-- SALT operators that are not core SALT (i.e. list operators and
-- occurring). These are defined as Haskell functions and are
-- expanded while constructing the core SALT syntax tree.

import SALT
import Common
import Timed

-- *********************************************************

data Range = Exactly SI Int 
           | Greater SI Int
           | Less SI Int
           | GreaterOrEqual SI Int
           | LessOrEqual SI Int
           | FromTo SI Int Int     
           
           deriving Eq      
           
instance Show Range where
  show (Exactly _ n) = "=" ++ (show n)		
  show (Greater _ n) = ">" ++ (show n)		
  show (Less _ n) = "<" ++ (show n)		
  show (GreaterOrEqual _ n) = ">=" ++ (show n)		
  show (LessOrEqual _ n) = "<=" ++ (show n)		
  show (FromTo _ n1 n2) = (show n1) ++ ".." ++ (show n2)		
			
-- *********************************************************

-- Helper function for repeat
repeatLessOrEqualHelper fp si n a =
  if (n == 1) then a
  else Or si a
             (Sequence fp si a (repeatLessOrEqualHelper fp si (n-1) a))

-- *********************************************************

-- This function is called by code inserted by the parser for enumerate
-- list creation. It creates a list of identifiers with the number n..m as names.
enumerate :: SI -> Range -> [Expr]
enumerate si (FromTo si2 from to) = 
                if (from > to) then []
                else (Ident si2 (show from)) : (enumerate si2 (FromTo si2 (from+1) to))
enumerate si r = [(Error si "enumerate must be used with a range n..m")]

-- This function is called by code inserted by the parser for list processing.
-- It takes a list and a unary function and creates a list of expressions
-- by calling the function each time with one list element.
inexpressions :: SI -> [Expr] -> (SI -> Expr -> Expr) -> [Expr]
inexpressions si [] f = []
inexpressions si (e : l) f = 
                 (f si e) : (inexpressions si l f)

allof :: SI -> [Expr] -> Expr 
allof si l = (implode si l And (TT si))

noneof :: SI -> [Expr] -> Expr 
noneof si l = (Not si (implode si l Or (FF si)))

someof :: SI -> [Expr] -> Expr 
someof si l = (implode si l Or (FF si))

exactlyoneof :: SI -> [Expr] -> Expr
exactlyoneof si l = (someof si (inexpressions si l (invtheonlyof l)))

without :: SI -> [Expr] -> Expr -> [Expr]
without si l e = if (l == []) then [(Error si "Expression is not in the list from which it should be excluded")]
                      else if ((head l) == e) then (withoutRest si (tail l) e)
                      else (head l) : (without si (tail l) e)

with :: SI -> [Expr] -> Expr -> [Expr]
with si l e = l ++ [e]

-- *** Helper:

implode :: SI -> [Expr] -> (SI -> Expr -> Expr -> Expr) -> Expr -> Expr
implode si l glue neutral = 
                if ((length l) == 0) then (neutral)
                else (glue si (head l) (implode si (tail l) glue neutral)) 
                        
invtheonlyof :: [Expr] -> SI -> Expr -> Expr
invtheonlyof l si e = (And si e (noneof si (without si l e)))

withoutRest :: SI -> [Expr] -> Expr -> [Expr]
withoutRest si l e = if (l == []) then []
                      else if ((head l) == e) then (withoutRest si (tail l) e)
                      else (head l) : (withoutRest si (tail l) e)

-- *********************************************************

-- never e => !eventually e
never fp si e = Not si (Eventually fp si e)

-- a releases n => a weakuntil a&b
releases fp si e1 e2 = Until fp si e2 (inclusive si (weak si e1))

-- nextn[=n] e = next next ... next e
nextn fp si (Exactly _ 0) e = e
nextn fp si (Exactly _ n) e = if (n < 0) then Error si "Number of nexts may not be negative"
  else Next fp si (nextn fp si (Exactly si (n-1)) e)

-- nextn[n1..n2]e  => nextn[=n] (nextn[<=n2-n1] e)
nextn fp si (FromTo si2 n1 n2) e = 
  if (n2 < n1) then Error si2 "Upper range bound may not be smaller than lower range bound" 
  else (nextn fp si (Exactly si (n1)) 
         (nextn fp si (LessOrEqual si (n2-n1)) e))
                
-- nextn[<= 0] e => e
-- nextn[<= n]e  => e | next (nextn[<= n-1] e)
nextn fp si (LessOrEqual si2 n) e = 
  if (n < 0) then Error si2 "Number of occurrences may not be negative" 
  else if (n == 0) then e
  else (Or si e
         (Next fp si (nextn fp si (LessOrEqual si (n-1)) e)))
                
-- nextn[<n] e => nextn[<=n-1] e
nextn fp si (Less si2 n) e = 
  if (n <= 0) then Error si2 "Number of nexts may not be negative"
  else (nextn fp si (LessOrEqual si (n-1)) e)

-- nextn[>=n] e => nextn[=n] eventually e
nextn fp si (GreaterOrEqual _ n) e = 
  (nextn fp si (Exactly si n) (Eventually fp si e))
  
-- nextn[>n] e => nextn[>=n+1] e
nextn fp si (Greater _ n) e = 
  (nextn fp si (GreaterOrEqual si (n+1)) e)

-- *********************************************************

-- occurring[=0] e => never e
-- occurring[=1] e => !e until (e & (e weakuntil never e))
-- occurring[=n] e => !e until (e & (e until (!e & (occurring[=n-1] e))))
occurring fp si (Exactly _ n) e =
    if (n <= 0) then (Not si (Eventually fp si e))
    else if (n == 1) then (Until fp si (Not si e) 
                            (And si e
                              (Until fp si e 
                                (Weak si (Not si (Eventually fp si e)))
                              )
                            )
                          )                           
      else (Until fp si (Not si e) 
             (And si e 
               (Until fp si e 
                 (And si (Not si e) 
                   (occurring fp si (Exactly si (n-1)) e)
                 )
               )
             )
           )
           
-- occurring[0..n] e => occurring[<=n] e
-- occurring[1..n] e => !e until (e & (e weakuntil (!e & occurring[<n] e)))
-- occurring[n1..n2] e => !e until (e & (e until (!e & (occurring[n1-1..n2-1] e))))
occurring fp si (FromTo si2 n1 n2) e =
    if (n2 < n1) then Error si2 "Upper range bound may not be smaller than lower range bound" 
    else if (n1 == 0) then (occurring fp si (LessOrEqual si n2) e)
      else if (n1 == 1) then (Until fp si (Not si e) 
                            (And si e
                              (Until fp si e 
                                (Weak si (And si (Not si e)
                                  (occurring fp si (Less si n2) e)
                                ))
                              )
                            )
                          )                           
      else (Until fp si (Not si e) 
             (And si e 
               (Until fp si e 
                 (And si (Not si e) 
                   (occurring fp si (FromTo si (n1-1) (n2-1)) e)
                 )
               )
             )
           )
           
-- occurring[<=n] e => !occurring[>=n+1]
occurring fp si (LessOrEqual si2 n) e =
  if (n < 0) then Error si2 "Number of occurrences may not be negative" 
  else Not si (occurring fp si (GreaterOrEqual si (n+1)) e)
           
-- occurring[<n] e => !occurring[>=n] e
occurring fp si (Less si2 n) e =
  if (n <= 0) then Error si2 "Number of occurrences may not be negative" 
  else Not si (occurring fp si (GreaterOrEqual si n) e)
  
-- occurring[>=0] e => true
-- occurring[>=1] e => eventually e
-- occurring[>=n] e => eventually (e & (eventually (!e & (occurring[>=n-1] e))))
occurring fp si (GreaterOrEqual _ n) e =
    if (n == 0) then TT si
    else if (n == 1) then (Eventually fp si e)                             
      else (Eventually fp si
             (And si e
               (Eventually fp si 
                 (And si (Not si e)
                   (occurring fp si (GreaterOrEqual si (n-1)) e)
                 )
               )
             )
           )
           
-- occurring[>n] e => occurring[>=n+1] e
occurring fp si (Greater _ n) e =
  (occurring fp si (GreaterOrEqual si (n+1)) e)

-- *********************************************************

-- holding[=0] e => never e
-- holding[=1] e => !e until (e & (weaknext never e))
-- holding[=n] e => !e until (e & (next (holding[=n-1] e)))
-- the case n=1 is necessary for cases where holding appears inside before
holding fp si (Exactly _ n) e =
    if (n <= 0) then (Not si (Eventually fp si e))
    else if (n == 1) then (Until fp si (Not si e) 
                            (And si e
                              (Next fp si (Weak si 
                                  (Not si (Eventually fp si e))
                              ))
                            )
                          )                           
      else (Until fp si (Not si e) 
             (And si e 
               (Next fp si  
                   (holding fp si (Exactly si (n-1)) e)
               )
             )
           )
           
-- holding[0..n] e => holding[<=n] e
-- holding[1..n2] e => !e until (e & weaknext (holding[<=n2-1] e))
-- holding[n1..n2] e => !e until (e & next (holding[n1-1..n2-1] e))
-- the case n1=1 is necessary for cases where holding appears inside before
holding fp si (FromTo si2 n1 n2) e =
    if (n2 < n1) then Error si2 "Upper range bound may not be smaller than lower range bound" 
    else if (n1 == 0) then (holding fp si (LessOrEqual si n2) e)
    else if (n1 == 1) then (Until fp si (Not si e) 
             (And si e 
               (Next fp si (Weak si 
                   (holding fp si (LessOrEqual si (n2-1)) e)
               ))
             )
           )
      else (Until fp si (Not si e) 
             (And si e 
               (Next fp si 
                   (holding fp si (FromTo si (n1-1) (n2-1)) e)
               )
             )
           )
           
-- holding[<=n] e => !holding[>=n+1] e
holding fp si (LessOrEqual si2 n) e =
  if (n < 0) then Error si2 "Number of occurrences may not be negative" 
  else Not si (holding fp si (GreaterOrEqual si (n+1)) e)
           
-- holding[<n] e => !holding[>=n] e
holding fp si (Less si2 n) e =
  if (n <= 0) then Error si2 "Number of occurrences may not be negative" 
  else Not si (holding fp si (GreaterOrEqual si n) e)
  
-- holding[>=0] e => true
-- holding[>=1] e => eventually e
-- holding[>=n] e => eventually (e & (next (holding[>=n-1] e))
holding fp si (GreaterOrEqual _ n) e =
    if (n == 0) then TT si 
    else if (n == 1) then (Eventually fp si e)                             
      else (Eventually fp si 
             (And si e
               (Next fp si 
                   (holding fp si (GreaterOrEqual si (n-1)) e)
               )
             )
           )
           
-- holding[>n] e => holding[>=n+1] e
holding fp si (Greater _ n) e =
  (holding fp si (GreaterOrEqual si (n+1)) e)

-- *********************************************************
-- The following functions help sorting qualfiers like incl, excl etc.
-- The correct order is (Timed) (Excl|Incl) (Req|Opt|Weak) (<Expression>)
-- Translation in SALT2RLTL relies on this ordering.

timed :: SI -> TimeRange -> Expr -> Expr
timed si r e = Timed si r e

exclusive :: SI -> Expr -> Expr
exclusive si (Timed si2 r e) = (SALTMacros.timed si2 r (SALTMacros.exclusive si e))
exclusive si e = Exclusive si e

inclusive :: SI -> Expr -> Expr
inclusive si (Timed si2 r e) = (SALTMacros.timed si2 r (SALTMacros.inclusive si e))
inclusive si e = Inclusive si e

required :: SI -> Expr -> Expr
required si (Timed si2 r e) = (SALTMacros.timed si2 r (SALTMacros.required si e))
required si (Inclusive si2 e) = (SALTMacros.inclusive si2 (SALTMacros.required si e))
required si (Exclusive si2 e) = (SALTMacros.exclusive si2 (SALTMacros.required si e))
required si e = Required si e
  
optional :: SI -> Expr -> Expr
optional si (Timed si2 r e) = (SALTMacros.timed si2 r (SALTMacros.optional si e))
optional si (Inclusive si2 e) = (SALTMacros.inclusive si2 (SALTMacros.optional si e))
optional si (Exclusive si2 e) = (SALTMacros.exclusive si2 (SALTMacros.optional si e))
optional si e = Optional si e
  
weak :: SI -> Expr -> Expr
weak si (Timed si2 r e) = (SALTMacros.timed si2 r (SALTMacros.weak si e))
weak si (Inclusive si2 e) = (SALTMacros.inclusive si2 (SALTMacros.weak si e))
weak si (Exclusive si2 e) = (SALTMacros.exclusive si2 (SALTMacros.weak si e))
weak si e = Weak si e

-- *********************************************************
-- Regular expression repeat statements are translated here

-- a*[=0] => //
-- a*[=1] => a
-- a*[=n] => a;a*[=n-1]
repeat fp si (Exactly si2 n) a =
  if (n < 0) then Error si "Number of repetitions may not be negative"
    else if (n == 0) then EmptySequence fp si 
      else if (n == 1) then a
        else Sequence fp si a (SALTMacros.repeat fp si (Exactly si2 (n-1)) a)
        
-- a*[0..n2]  => a*[<=n2]
-- a*[n1..n2]  => (a*[=n1-1]; a*[<=n2-n1]; a) 
-- the last extra a is for correct translation of a following : sequence op
repeat fp si (FromTo si2 n1 n2) a  = 
  if (n2 < n1) then Error si2 "Upper range bound may not be smaller than lower range bound" 
  else if (n1 == 0) then
                   (SALTMacros.repeat fp si (LessOrEqual si2 n2) a) 
  else Sequence fp si (SALTMacros.repeat fp si (Exactly si2 (n1-1)) a)
         (Sequence fp si 
           (SALTMacros.repeat fp si (LessOrEqual si2 (n2-n1)) a) 
           a
         )

-- a*[<=0] => //
-- a*[<=n] => // | (a | X (a | X (...)))
-- here we need a helper function in oder to ensure correct translation of
-- a following :
repeat fp si (LessOrEqual si2 n) a =  
  if (n <= 0) then EmptySequence fp si 
  else Or si (EmptySequence fp si)
       (repeatLessOrEqualHelper fp si n a)

-- a*[<n] => a*[<=n-1]
repeat fp si (Less si2 n) a =  
  if (n <= 0) then Error si2 "Number of repetitions may not be negative" 
  else SALTMacros.repeat fp si (LessOrEqual si2 (n-1)) a

repeat fp si (GreaterOrEqual si2 n) a =
  RepeatGreaterOrEqual fp si n a
         
-- a*[>n] => a*[>n+1]
repeat fp si (Greater si2 n) a =
  SALTMacros.repeat fp si (GreaterOrEqual si2 (n+1)) a
  
  