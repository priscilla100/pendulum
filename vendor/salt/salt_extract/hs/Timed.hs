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

module Timed (TimeRange (..)) where

-- This module defines data for timed LTL that are used by
-- SALT.hs, RLTL.hs and LTL.hs

import Common

-- *********************************************************

data TimeRange = TimeExactly SI Float 
               | TimeGreater SI Float
               | TimeLess SI Float
               | TimeGreaterOrEqual SI Float
               | TimeLessOrEqual SI Float
           
           deriving Eq      
           
instance Show TimeRange where
  show (TimeExactly _ n) = "=" ++ (show n)		
  show (TimeGreater _ n) = ">" ++ (show n)		
  show (TimeLess _ n) = "<" ++ (show n)		
  show (TimeGreaterOrEqual _ n) = ">=" ++ (show n)		
  show (TimeLessOrEqual _ n) = "<=" ++ (show n)		
