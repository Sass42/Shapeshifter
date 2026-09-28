-- mod-shapeshifter: auras a transformed player's form spells may have left on them, so a login
-- after a crash can strip them (the periodic character save may have persisted them). One row per
-- transformed character, deleted on revert. Apply to acore_characters by hand: the repack runs
-- with database updates off. Replaces the table's old name (shapeshift_active).
CREATE TABLE IF NOT EXISTS `shapeshifter_active` (
  `guid` INT UNSIGNED NOT NULL,
  `auras` VARCHAR(1024) NOT NULL DEFAULT '',
  PRIMARY KEY (`guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
DROP TABLE IF EXISTS `shapeshift_active`;
