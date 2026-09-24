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

module LTL2SMVTest (LTL2SMVTest.printLTL) where

-- *******************************************************
-- This module defines the function printLTL for printing
-- a LTL formula in SMV output format with ProMeLa generation.
-- *******************************************************

import LTL
import Common
import OptimizeLTL
import Helper
import List
import Timed
import LTL2SMV


-- *******************************************************

printLTL :: TimedOutputSyntax -> 
            PastConstraint -> NextConstraint -> Expr -> IO()
printLTL tos pc nc e = 
           let i = nub (findIdent e) in printCompilationResult (
             Output "MODULE main \n" `cons`
             Output "VAR \n" `cons`
             (printVarDecl i) `cons`
             Output "ASSIGN \n" `cons`
             (printVarAssign i) `cons`
             Output "\n" `cons`
             Output "LTLSPEC \n$$$\n" `cons` 
             (LTL2SMV.convertLTL2Out tos pc nc e) `cons` 
             Output "))\n")


-- *******************************************************
-- Helper functions for SMVTest
-- *******************************************************

printVarDecl :: [String] -> CompilationResult
printVarDecl [] = Output ""
printVarDecl l = Output (head l) `cons`
                 Output " : boolean;\n" `cons`
                 if ((length l) > 1) then printVarDecl (tail l)
                 else Output ""

printVarAssign :: [String] -> CompilationResult
printVarAssign [] = Output ""
printVarAssign l = Output "init(" `cons`
                   Output (head l) `cons`
                   Output ") := {0, 1};\n" `cons`
                   Output "next(" `cons`
                   Output (head l) `cons`
                   Output ") := {0, 1};\n" `cons`
                   if ((length l) > 1) then printVarAssign (tail l)
                   else Output ""

findIdent :: Expr -> [String]
findIdent (Ident _ i) = i : [] 
findIdent (TT _) = []
findIdent (FF _) = []
findIdent (Or _ o1 o2) = (findIdent o1) ++ (findIdent o2) 
findIdent (And _ a1 a2) = (findIdent a1) ++ (findIdent a2) 
findIdent (Equ _ a1 a2) = (findIdent a1) ++ (findIdent a2) 
findIdent (Impl _ a1 a2) = (findIdent a1) ++ (findIdent a2) 
findIdent (Not _ n) = findIdent n  
findIdent (Until fp _ u1 u2) = (findIdent u1) ++ (findIdent u2)
findIdent (WeakUntil fp _ u1 u2) = (findIdent u1) ++ (findIdent u2)
findIdent (Next fp _ n) = findIdent n  
findIdent (Always fp _ n) = findIdent n  
findIdent (Eventually fp _ n) = findIdent n  
findIdent (TPredict fp _ r n) = findIdent n  
findIdent (TUntil fp _ r u1 u2) = (findIdent u1) ++ (findIdent u2)
findIdent (TWeakUntil fp _ r u1 u2) = (findIdent u1) ++ (findIdent u2)
findIdent (TAlways fp _ r n) = findIdent n  
findIdent (TEventually fp _ r n) = findIdent n  
findIdent (Error _ e) = []

