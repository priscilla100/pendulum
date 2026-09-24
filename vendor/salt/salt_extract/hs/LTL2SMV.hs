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

module LTL2SMV where

-- *******************************************************
-- This module defines the function printLTL for printing
-- a LTL formula in SMV output format.
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
               Output "LTLSPEC " `cons`
               (convertLTL2Out tos pc nc e) `cons` 
               Output "\n")

-- *******************************************************
-- Conversion function
-- *******************************************************

convertLTL2Out :: TimedOutputSyntax -> 
           PastConstraint -> NextConstraint -> Expr -> CompilationResult

convertLTL2Out tos WithoutPast nc (Until Past si u1 u2) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (WeakUntil Past si u1 u2) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (Next Past si n) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (Always Past si n) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (Eventually Past si n) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (TPredict Past si r n) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (TUntil Past si r u1 u2) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (TWeakUntil Past si r u1 u2) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (TAlways Past si r n) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]
convertLTL2Out tos WithoutPast nc (TEventually Past si r n) = 
  Errors ["Past operators were forbidden for translation at " ++ (show si)]

convertLTL2Out tos pc WithoutNext (Next fp si n) = 
  Errors ["Next operators were forbidden for translation at " ++ (show si)]

convertLTL2Out WithoutTimed pc nc (TPredict fp si r e) = 
  Errors ["Timed operators were forbidden for translation at " ++ (show si)]
convertLTL2Out WithoutTimed pc nc (TWeakUntil fp si r u1 u2) = 
  Errors ["Timed operators were forbidden for translation at " ++ (show si)]
convertLTL2Out WithoutTimed pc nc (TUntil fp si r u1 u2) = 
  Errors ["Timed operators were forbidden for translation at " ++ (show si)]
convertLTL2Out WithoutTimed pc nc (TAlways fp si r e) = 
  Errors ["Timed operators were forbidden for translation at " ++ (show si)]
convertLTL2Out WithoutTimed pc nc (TEventually fp si r e) = 
  Errors ["Timed operators were forbidden for translation at " ++ (show si)]

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

convertLTL2Out tos pc nc (Ident si "G") = Errors ["Variable name clashes with SMV operator at " ++ (show si)]
convertLTL2Out tos pc nc (Ident si "F") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "U") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "R") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "X") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "H") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "O") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "S") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "T") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "Y") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 
convertLTL2Out tos pc nc (Ident si "Z") = Errors ["Variable name clashes with SMV operator at " ++ (show si)] 

convertLTL2Out tos pc nc (Ident _ i) = Output i 
convertLTL2Out tos pc nc (TT _)= Output "1" 
convertLTL2Out tos pc nc (FF _)= Output "0"
convertLTL2Out tos pc nc (Or _ o1 o2) = 
                      convertArg tos pc nc o1 `cons`
        		      Output " | " `cons`
                      convertArg tos pc nc o2 
convertLTL2Out tos pc nc (And _ a1 a2) = 
                       convertArg tos pc nc a1 `cons`
                       Output " & " `cons`
                       convertArg tos pc nc a2 
convertLTL2Out tos pc nc (Equ _ a1 a2) = 
                       convertArg tos pc nc a1 `cons`
                       Output " <-> " `cons`
                       convertArg tos pc nc a2 
convertLTL2Out tos pc nc (Impl _ a1 a2) = 
                        convertArg tos pc nc a1 `cons`
                        Output " -> " `cons`
                        convertArg tos pc nc a2 
convertLTL2Out tos pc nc (Not _ (Until Future _ (Not _ u1) (Not _ u2))) = 
                         convertArg tos pc nc u1 `cons`
                         Output " V " `cons`
                         convertArg tos pc nc u2 
convertLTL2Out tos pc nc (Not _ (Until Past _ (Not _ u1) (Not _ u2))) = 
                         convertArg tos pc nc u1 `cons`
                         Output " T " `cons`
                         convertArg tos pc nc u2 
convertLTL2Out tos pc nc (Not _ n) = Output "!" `cons`
                         convertArg tos pc nc n  
convertLTL2Out tos pc nc (WeakUntil fp si u1 u2) = convertLTL2Out tos pc nc (replaceWeakUntilByBest fp si u1 u2)
convertLTL2Out tos pc nc (Until Future _ u1 u2) = 
                         convertArg tos pc nc u1 `cons`
                         Output " U " `cons`
                         convertArg tos pc nc u2 
convertLTL2Out tos pc nc (Next Future _ n) = Output "X " `cons`
                    convertArg tos pc nc n 
convertLTL2Out tos pc nc (Always Future _ n) = Output "G " `cons`
                    convertArg tos pc nc n 
convertLTL2Out tos pc nc (Eventually Future _ n) = Output "F " `cons`
                    convertArg tos pc nc n 
convertLTL2Out tos pc nc (Until Past _ u1 u2) = 
                         convertArg tos pc nc u1 `cons`
                         Output " S " `cons`
                         convertArg tos pc nc u2 
convertLTL2Out tos pc nc (Next Past _ n) = Output "Y " `cons`
                    convertArg tos pc nc n 
convertLTL2Out tos pc nc (Always Past _ n) = Output "H " `cons`
                    convertArg tos pc nc n 
convertLTL2Out tos pc nc (Eventually Past _ n) = Output "O " `cons`
                    convertArg tos pc nc n 

convertLTL2Out tos pc nc (TPredict Future _ r e) = Output "|>[" `cons`
                    Output (show r) `cons` 
                    Output "] " `cons`
                    convertArg TLTL pc nc e 
convertLTL2Out tos pc nc (TPredict Past _ r e) = Output "<|[" `cons`
                    Output (show r) `cons` 
                    Output "] " `cons`
                    convertArg TLTL pc nc e 

convertLTL2Out TLTL pc nc (TUntil fp si r u1 u2) = convertLTL2Out TLTL pc nc (replaceTUntilByTPredict fp si r u1 u2) 
convertLTL2Out TLTL pc nc (TWeakUntil fp si r u1 u2) = convertLTL2Out TLTL pc nc (replaceTWeakUntilForOutput fp si r u1 u2) 
convertLTL2Out TLTL pc nc (TAlways fp si r e) = convertLTL2Out TLTL pc nc (replaceTAlwaysByTPredict fp si r e) 
convertLTL2Out TLTL pc nc (TEventually fp si r e) = convertLTL2Out TLTL pc nc (replaceTEventuallyByTPredict fp si r e) 

convertLTL2Out ExtendedTLTL pc nc (TUntil Future si r u1 u2) =  
                    convertArg ExtendedTLTL pc nc u1 `cons`
                    Output " U[" `cons`
                    Output (show r) `cons`
                    Output "] " `cons`
                    convertArg ExtendedTLTL pc nc u2 
convertLTL2Out ExtendedTLTL pc nc (TUntil Past si r u1 u2) =  
                    convertArg ExtendedTLTL pc nc u1 `cons`
                    Output " S[" `cons`
                    Output (show r) `cons`
                    Output "] " `cons`
                    convertArg ExtendedTLTL pc nc u2 
convertLTL2Out ExtendedTLTL pc nc (TWeakUntil fp si r u1 u2) = convertLTL2Out ExtendedTLTL pc nc (replaceTWeakUntilForOutput fp si r u1 u2)
convertLTL2Out ExtendedTLTL pc nc (TAlways Future _ r e) = 
                    Output "G[" `cons`
                    Output (show r) `cons` 
                    Output "] " `cons`
                    convertArg ExtendedTLTL pc nc e 
convertLTL2Out ExtendedTLTL pc nc (TAlways Past _ r e) = 
                    Output "H[" `cons`
                    Output (show r) `cons` 
                    Output "] " `cons`
                    convertArg ExtendedTLTL pc nc e 
convertLTL2Out ExtendedTLTL pc nc (TEventually Future _ r e) = 
                    Output "F[" `cons`
                    Output (show r) `cons` 
                    Output "] " `cons`
                    convertArg ExtendedTLTL pc nc e 
convertLTL2Out ExtendedTLTL pc nc (TEventually Past _ r e) = 
                    Output "O[" `cons`
                    Output (show r) `cons` 
                    Output "] " `cons`
                    convertArg ExtendedTLTL pc nc e 

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



