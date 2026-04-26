const homePage = require('../support/pages/homePage');
const navigation = require('../support/pages/navigation');

describe('Navigation', () => {
  it('User navigates through the main sections using the sticky header', () => {
    homePage.visit();
    navigation.getAboutLink().click();
    navigation.getProjectsLink().click();
    navigation.getContactLink().click();
  });
});