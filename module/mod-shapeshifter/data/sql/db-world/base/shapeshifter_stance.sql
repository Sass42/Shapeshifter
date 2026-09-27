-- mod-shapeshifter: a class-grade form's weapon stances (deep pass B2). One row per stance of a form's
-- gear set: the stance's name, the gear set holding its weapons, its bonus family and its own
-- abilities' families (csv of family numbers k; a family's spells are 14,000,000 + 20k onwards).
-- The class-grade build fills it (tools/gen_shapeshift_class.py --build); apply this file first.
CREATE TABLE IF NOT EXISTS `shapeshifter_stance` (
  `gear_set` SMALLINT UNSIGNED NOT NULL,
  `stance` TINYINT UNSIGNED NOT NULL,
  `name` VARCHAR(40) NOT NULL DEFAULT '',
  `weapon_set` SMALLINT UNSIGNED NOT NULL,
  `bonus` INT UNSIGNED NOT NULL DEFAULT 0,
  `abilities` VARCHAR(255) NOT NULL DEFAULT '',
  PRIMARY KEY (`gear_set`, `stance`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
