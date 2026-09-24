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

module Common (FP(..), SI(..), TimedOutputSyntax (..), PastConstraint (..),
  NextConstraint(..))where

-- This module defines data structures common for SALT, RLTL and LTL.
-- Part of this module is the SI class, which stands for SourceInfo.
-- It tracks the original reference position in the source code
-- for any SALT, RLTL or LTL element.

-- This is used for temporal operators to decide whether they are future or past operators
data FP = Future | Past
  deriving Eq
  
instance Show FP where
  show (Future) = ""		
  show (Past) = "inpast"		

-- Source Info: this is used to track source code information within the abstract syntax tree
data SI = Position Int Int
        
instance Show SI where
  show (Position l c) = "line " ++ (show l) ++ ":" ++ (show c)		

-- Two elements representing the same formula
-- with different positions in source code must still be equal in the sense
-- of ==. In order to avoid redefining Eq for all Expr, we define 
-- two SI to be always equal.
instance Eq SI where
  a == b = True		
  a /= b = False  
        
-- parameter for printLTL
data TimedOutputSyntax = WithoutTimed | TLTL | ExtendedTLTL

-- parameter for printLTL
data PastConstraint = WithPast | WithoutPast

-- parameter for printLTL
data NextConstraint = WithNext | WithoutNext

        