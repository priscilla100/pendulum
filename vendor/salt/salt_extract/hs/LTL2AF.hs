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

module LTL2AF where

-- *******************************************************
-- This module defines the function printLTL for printing
-- a LTL formula in AutoFocus2 output format.
-- *******************************************************

import LTL
import Common
import OptimizeLTL
import Helper
import List
import Timed

-- *******************************************************

printLTL :: TimedOutputSyntax -> 
            PastConstraint -> NextConstraint -> Expr -> IO()
printLTL tos pc nc e = 
             printCompilationResult (
                (convertLTL2Out tos pc nc e) `cons` 
                Output "\n")                

-- *******************************************************
-- Conversion function
-- *******************************************************

convertLTL2Out :: TimedOutputSyntax -> 
           PastConstraint -> NextConstraint -> Expr -> CompilationResult

convertLTL2Out tos pc WithoutNext (Next fp si n) = 
  Errors ["Next operators were forbidden for translation at " ++ (show si)]

convertLTL2Out tos pc nc (TEventually fp si (TimeExactly si2 t) e) = 
  Errors ["timed with = may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TEventually fp si (TimeGreaterOrEqual si2 t) e) = 
  Errors ["timed with >= may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TEventually fp si (TimeGreater si2 t) e) = 
  Errors ["timed with > may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TAlways fp si (TimeExactly si2 t) e) = 
  Errors ["timed with = may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TAlways fp si (TimeGreaterOrEqual si2 t) e) = 
  Errors ["timed with >= may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TAlways fp si (TimeGreater si2 t) e) = 
  Errors ["timed with > may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TUntil fp si (TimeExactly si2 t) e1 e2) = 
  Errors ["timed with = may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TUntil fp si (TimeGreaterOrEqual si2 t) e1 e2) = 
  Errors ["timed with >= may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TUntil fp si (TimeGreater si2 t) e1 e2) = 
  Errors ["timed with > may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TWeakUntil fp si (TimeExactly si2 t) e1 e2) = 
  Errors ["timed with = may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TWeakUntil fp si (TimeGreaterOrEqual si2 t) e1 e2) = 
  Errors ["timed with >= may only be used in connection with next or nextinpast at " ++ (show si)]
convertLTL2Out tos pc nc (TWeakUntil fp si (TimeGreater si2 t) e1 e2) = 
  Errors ["timed with > may only be used in connection with next or nextinpast at " ++ (show si)]

convertLTL2Out tos pc nc (Error si s) = Errors [s ++ " at " ++ (show si)]

-- *******************************************************


convertLTL2Out tos pc nc (Until Past si u1 u2) = Errors ["AutoFocus output does not allow past operators at " ++ (show si)]
convertLTL2Out tos pc nc (WeakUntil Past si u1 u2) = Errors ["AutoFocus output does not allow past operators at " ++ (show si)]
convertLTL2Out tos pc nc (Next Past si n) = Errors ["AutoFocus output does not allow past operators at " ++ (show si)]
convertLTL2Out tos pc nc (Always Past si n) = Errors ["AutoFocus output does not allow past operators at " ++ (show si)]
convertLTL2Out tos pc nc (Eventually Past si n) = Errors ["AutoFocus output does not allow past operators at " ++ (show si)]

convertLTL2Out tos pc nc (TPredict _ si r e) = Errors ["AutoFocus output does not allow timed operators at " ++ (show si)]
convertLTL2Out tos pc nc (TUntil _ si r u1 u2) = Errors ["AutoFocus output does not allow timed operators at " ++ (show si)]
convertLTL2Out tos pc nc (TWeakUntil _ si r u1 u2) = Errors ["AutoFocus output does not allow timed operators at " ++ (show si)]
convertLTL2Out tos pc nc (TAlways _ si r n) = Errors ["AutoFocus output does not allow timed operators at " ++ (show si)]
convertLTL2Out tos pc nc (TEventually _ si r n) = Errors ["AutoFocus output does not allow timed operators at " ++ (show si)]

convertLTL2Out tos pc nc (Ident _ i) = Output ("(" ++ i ++ ")")
convertLTL2Out tos pc nc (TT _) = Output "True" 
convertLTL2Out tos pc nc (FF _) = Output "False"
convertLTL2Out tos pc nc (Or _ o1 o2) = 
                      convertArg tos pc nc o1 `cons`
        		      Output " || " `cons`
                      convertArg tos pc nc o2 
convertLTL2Out tos pc nc (And _ a1 a2) = 
                       convertArg tos pc nc a1 `cons`
                       Output " && " `cons`
                       convertArg tos pc nc a2 
convertLTL2Out tos pc nc (Equ _ a1 a2) = 
                       convertArg tos pc nc a1 `cons`
                       Output " <=> " `cons`
                       convertArg tos pc nc a2 
convertLTL2Out tos pc nc (Impl _ a1 a2) = 
                        convertArg tos pc nc a1 `cons`
                        Output " => " `cons`
                        convertArg tos pc nc a2 
convertLTL2Out tos pc nc (Not _ n) = Output "!" `cons`
                         convertArg tos pc nc n  
convertLTL2Out tos pc nc (Until Future _ u1 u2) =
                         convertArg tos pc nc u1 `cons`
                         Output " |_| " `cons`
                         convertArg tos pc nc u2 
convertLTL2Out tos pc nc (WeakUntil Future  si u1 u2) = convertLTL2Out tos pc nc (replaceWeakUntilByBest Future si u1 u2)
convertLTL2Out tos pc nc (Next fp _ n) = Output "()" `cons`
                    convertArg tos pc nc n 
convertLTL2Out tos pc nc (Always fp _ n) = Output "[]" `cons`
                    convertArg tos pc nc n 
convertLTL2Out tos pc nc (Eventually fp _ n) = Output "<>" `cons`
                    convertArg tos pc nc n 


-- *******************************************************
-- Helper function for putting correct parantheses
-- *******************************************************
-- This function puts parentheses around the argument "if necessary".
-- As e.g. nuSMV and Cadence SMV use different operator precedences,
-- parentheses are almost always necessary.

convertArg :: TimedOutputSyntax -> 
           PastConstraint -> NextConstraint -> Expr -> CompilationResult
-- convertArg tos pc nc (Not si (Ident si2 i)) = convertLTL2Out tos pc nc (Not si (Ident si2 i))
-- convertArg tos pc nc (Not si (TT si2)) = convertLTL2Out tos pc nc (Not si (TT si2))
-- convertArg tos pc nc (Not si (FF si2)) = convertLTL2Out tos pc nc (Not si (FF si2))
convertArg tos pc nc (Ident si i) = convertLTL2Out tos pc nc (Ident si i)
convertArg tos pc nc (TT si) = convertLTL2Out tos pc nc (TT si)
convertArg tos pc nc (FF si) = convertLTL2Out tos pc nc (FF si)
convertArg tos pc nc e = Output "(" `cons`
                            convertLTL2Out tos pc nc e `cons`
                            Output ")"

