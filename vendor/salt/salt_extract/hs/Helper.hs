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

module Helper where

-- This module includes various helpful functions.
--

import LTL
import RLTL
import SALT
import IO
import List

printRLTL :: RLTL.Expr -> IO()
printRLTL e = putStr (show e) >> putStr "\n"

-- This datatype is used when printing out results and collecting the errors
-- within the formula. It either represents a String
-- ready to be printed or a collection of error
-- messages
data CompilationResult = Output String 
                       | Errors [String]

-- Concatenates two CompilationResult objects.
-- Concatenation of error-containing formulae always 
-- produces an Errors as result
cons :: CompilationResult -> CompilationResult -> CompilationResult
(Output s) `cons` (Output t) = Output (s++t)
(Output s) `cons` (Errors e) = Errors e
(Errors e) `cons` (Output s) = Errors e
(Errors e) `cons` (Errors f) = Errors (e++f)

-- This function prints error messages that occured when compiling
-- a formula or the result when no errors occured
printCompilationResult :: CompilationResult -> IO ()
printCompilationResult (Output s) = putStr s
printCompilationResult (Errors e) = printErrorList (nub e)

printErrorList :: [String] -> IO()
printErrorList l = if ((length l) == 0) then putStr ""
                   else hPutStrLn stderr (head l) >> printErrorList (tail l)

			
                   