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

module PropositionCheck where

import SALT
import Common
import List
import Maybe

-- This function parses a string that is used as a boolean proposition
-- into an Ident.
-- In the default implementation, it checks whether all variables
-- have been declared (if a declare statement exists in the spec).
-- If no declare exists, it does nothing.
parseProposition :: SI -> String -> [String] -> Expr
parseProposition si s [] = Ident si s
parseProposition si s declared = 
  if (isNothing (find (s ==) declared)) then Error si ("Variable " ++ s ++ " was not declared")
  else Ident si s


