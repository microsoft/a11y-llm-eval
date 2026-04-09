const { getAccessibleName } = require('./get-accessibility-tree');

const getName = async (el) => {
    return getAccessibleName(el);
}

module.exports = getName;