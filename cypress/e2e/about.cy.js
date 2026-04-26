const aboutPage = require('../support/pages/aboutPage');

describe('About Page', () => {
  it('User navigates to the About page', () => {
    const homePage = require('../support/pages/homePage');
    homePage.visit();
    homePage.getAboutLink().first().click();
    aboutPage.getBiographySection().should('be.visible');
    aboutPage.getEducationSection().should('be.visible');
    aboutPage.getExperienceSection().should('be.visible');
  });
});